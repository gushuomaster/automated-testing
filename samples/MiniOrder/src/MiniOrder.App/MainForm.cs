using System.Globalization;
using MiniOrder.Core;

namespace MiniOrder.App;

public sealed class MainForm : Form
{
    private readonly OrderService _service;
    private readonly OrderValidator _validator;
    private readonly OrderAmountCalculator _calculator;
    private readonly ErrorProvider _errors = new();
    private readonly TextBox _customer = CreateTextBox("CustomerNameInput", "客户名称");
    private readonly TextBox _product = CreateTextBox("ProductNameInput", "商品名称");
    private readonly TextBox _quantity = CreateTextBox("QuantityInput", "数量");
    private readonly TextBox _unitPrice = CreateTextBox("UnitPriceInput", "单价");
    private readonly TextBox _amount = CreateTextBox("OrderAmountOutput", "订单金额", readOnly: true);
    private readonly Label _formStatus = CreateStatusLabel("OrderFormStatus", "订单录入状态");
    private readonly TextBox _keyword = CreateTextBox("QueryKeywordInput", "查询关键字");
    private readonly ComboBox _statusFilter = new()
    {
        Name = "StatusFilter",
        AccessibleName = "订单状态筛选",
        DropDownStyle = ComboBoxStyle.DropDownList,
        Dock = DockStyle.Fill
    };
    private readonly DataGridView _results = new()
    {
        Name = "OrderResultsGrid",
        AccessibleName = "订单查询结果",
        Dock = DockStyle.Fill,
        ReadOnly = true,
        AllowUserToAddRows = false,
        AllowUserToDeleteRows = false,
        AllowUserToResizeRows = false,
        AutoGenerateColumns = false,
        AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
        MultiSelect = false,
        RowHeadersVisible = false,
        SelectionMode = DataGridViewSelectionMode.FullRowSelect
    };
    private readonly Label _resultCount = CreateStatusLabel("QueryResultCount", "查询结果数量");
    private readonly Button _saveButton = CreateButton("SaveOrderButton", "保存订单", 5);
    private readonly Button _queryButton = CreateButton("QueryOrdersButton", "查询", 2);
    private readonly ToolStripStatusLabel _applicationStatus = new()
    {
        Name = "ApplicationStatus",
        AccessibleName = "应用状态",
        Text = "就绪"
    };

    public MainForm(OrderService service, OrderValidator validator, OrderAmountCalculator calculator)
    {
        _service = service;
        _validator = validator;
        _calculator = calculator;

        Name = "MiniOrderMainWindow";
        AccessibleName = "MiniOrder 主窗口";
        Text = $"{ProductInfo.Name} - 订单管理";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(900, 620);
        Size = new Size(1040, 700);
        AutoScaleMode = AutoScaleMode.Dpi;

        _errors.ContainerControl = this;
        _errors.BlinkStyle = ErrorBlinkStyle.NeverBlink;
        var tabs = BuildTabs();
        tabs.SelectedIndexChanged += (_, _) => UpdateAcceptButton(tabs);
        Controls.Add(tabs);
        Controls.Add(new StatusStrip { Name = "MainStatusStrip", AccessibleName = "主状态栏", Items = { _applicationStatus } });
        UpdateAcceptButton(tabs);

        _quantity.TextChanged += (_, _) => UpdateAmount();
        _unitPrice.TextChanged += (_, _) => UpdateAmount();
        Shown += (_, _) =>
        {
            tabs.SelectedIndex = 0;
            UpdateAcceptButton(tabs);
            _customer.Focus();
        };
    }

    private TabControl BuildTabs()
    {
        var tabs = new TabControl
        {
            Name = "MainTabs",
            AccessibleName = "订单工作区",
            Dock = DockStyle.Fill
        };
        tabs.TabPages.Add(BuildCreatePage());
        tabs.TabPages.Add(BuildQueryPage());
        tabs.SelectedIndex = 0;
        return tabs;
    }

    private TabPage BuildCreatePage()
    {
        var page = new TabPage("新建订单") { Name = "CreateOrderTab", AccessibleName = "新建订单" };
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            Padding = new Padding(24),
            ColumnCount = 2,
            RowCount = 7
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 130));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

        AddField(layout, 0, "客户名称（必填）", "CustomerNameLabel", _customer, 0);
        AddField(layout, 1, "商品名称（必填）", "ProductNameLabel", _product, 1);
        AddField(layout, 2, "数量（1～999）", "QuantityLabel", _quantity, 2);
        AddField(layout, 3, "单价", "UnitPriceLabel", _unitPrice, 3);
        AddField(layout, 4, "订单金额", "OrderAmountLabel", _amount, 4);

        var buttons = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight };
        var clear = CreateButton("ClearOrderButton", "清空", 6);
        _saveButton.Click += (_, _) => SaveOrder();
        clear.Click += (_, _) => ClearForm();
        buttons.Controls.Add(_saveButton);
        buttons.Controls.Add(clear);
        layout.Controls.Add(buttons, 1, 5);
        layout.Controls.Add(_formStatus, 1, 6);
        page.Controls.Add(layout);
        return page;
    }

    private TabPage BuildQueryPage()
    {
        ConfigureColumns();
        _statusFilter.Items.AddRange(["全部", ProductInfo.NewStatus]);
        _statusFilter.SelectedIndex = 0;
        _statusFilter.TabIndex = 1;

        var page = new TabPage("查询订单") { Name = "QueryOrderTab", AccessibleName = "查询订单" };
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(16), ColumnCount = 4, RowCount = 3 };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 60));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 40));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        layout.Controls.Add(CreateLabel("查询关键字", "QueryKeywordLabel"), 0, 0);
        _keyword.TabIndex = 0;
        layout.Controls.Add(_keyword, 1, 0);
        layout.Controls.Add(CreateLabel("订单状态", "StatusFilterLabel"), 2, 0);
        layout.Controls.Add(_statusFilter, 3, 0);

        var actions = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Bottom };
        var clear = CreateButton("ClearFiltersButton", "清除筛选", 3);
        _queryButton.Click += (_, _) => RefreshResults();
        clear.Click += (_, _) => { _keyword.Clear(); _statusFilter.SelectedIndex = 0; RefreshResults(); };
        actions.Controls.Add(_queryButton);
        actions.Controls.Add(clear);
        layout.Controls.Add(actions, 0, 2);
        layout.SetColumnSpan(actions, 2);
        layout.Controls.Add(_resultCount, 2, 2);
        layout.SetColumnSpan(_resultCount, 2);
        layout.Controls.Add(_results, 0, 1);
        layout.SetColumnSpan(_results, 4);
        page.Controls.Add(layout);
        page.Enter += (_, _) => RefreshResults();
        return page;
    }

    private void SaveOrder()
    {
        ClearErrors();
        var result = _service.Create(CurrentDraft());
        if (!result.IsSuccess)
        {
            ShowIssues(result.Issues);
            SetStatus(_formStatus, "保存失败：请修正标出的字段。");
            _applicationStatus.Text = "订单未保存";
            FocusFirstIssue(result.Issues);
            return;
        }

        SetStatus(_formStatus, $"保存成功：{result.Order!.OrderNumber}，状态：{result.Order.Status}");
        _applicationStatus.Text = "订单已保存";
        ClearInputs(preserveStatus: true);
    }

    private void UpdateAmount()
    {
        var result = _validator.Validate(new OrderDraft("占位客户", "占位商品", _quantity.Text, _unitPrice.Text));
        var operandsValid = result.Issues.All(issue => issue.Field is not ("Quantity" or "UnitPrice"));
        _amount.Text = operandsValid && result.Value is not null
            ? _calculator.Calculate(result.Value.Quantity, result.Value.UnitPrice).ToString("F2", CultureInfo.InvariantCulture)
            : string.Empty;
    }

    private void ClearForm()
    {
        ClearInputs(preserveStatus: false);
        _applicationStatus.Text = "表单已清空";
    }

    private void ClearInputs(bool preserveStatus)
    {
        _customer.Clear();
        _product.Clear();
        _quantity.Clear();
        _unitPrice.Clear();
        _amount.Clear();
        ClearErrors();
        if (!preserveStatus)
        {
            SetStatus(_formStatus, string.Empty);
        }
        _customer.Focus();
    }

    private void RefreshResults()
    {
        var status = _statusFilter.SelectedIndex <= 0 ? null : _statusFilter.SelectedItem?.ToString();
        var orders = _service.Query(_keyword.Text, status);
        _results.Rows.Clear();
        foreach (var order in orders)
        {
            _results.Rows.Add(
                order.OrderNumber,
                order.CustomerName,
                order.ProductName,
                order.Quantity.ToString(CultureInfo.InvariantCulture),
                order.UnitPrice.ToString("F2", CultureInfo.InvariantCulture),
                order.Amount.ToString("F2", CultureInfo.InvariantCulture),
                order.Status,
                order.CreatedAt.LocalDateTime.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture));
        }
        SetStatus(_resultCount, $"找到 {orders.Count} 条订单");
        _applicationStatus.Text = "查询完成";
    }

    private void ConfigureColumns()
    {
        AddColumn("OrderNumber", "订单编号");
        AddColumn("CustomerName", "客户名称");
        AddColumn("ProductName", "商品名称");
        AddColumn("Quantity", "数量");
        AddColumn("UnitPrice", "单价");
        AddColumn("Amount", "订单金额");
        AddColumn("Status", "状态");
        AddColumn("CreatedAt", "创建时间");
    }

    private void UpdateAcceptButton(TabControl tabs) =>
        AcceptButton = tabs.SelectedIndex == 0 ? _saveButton : _queryButton;

    private void AddColumn(string name, string header) =>
        _results.Columns.Add(new DataGridViewTextBoxColumn { Name = name, HeaderText = header, SortMode = DataGridViewColumnSortMode.NotSortable });

    private OrderDraft CurrentDraft() => new(_customer.Text, _product.Text, _quantity.Text, _unitPrice.Text);

    private void ShowIssues(IEnumerable<ValidationIssue> issues)
    {
        foreach (var issue in issues)
        {
            var control = ControlFor(issue.Field);
            if (control is not null)
            {
                _errors.SetError(control, issue.Message);
                control.AccessibleDescription = issue.Message;
            }
        }
    }

    private void ClearErrors()
    {
        _errors.Clear();
        foreach (var control in new Control[] { _customer, _product, _quantity, _unitPrice })
        {
            control.AccessibleDescription = string.Empty;
        }
    }

    private void FocusFirstIssue(IReadOnlyList<ValidationIssue> issues) => ControlFor(issues[0].Field)?.Focus();

    private Control? ControlFor(string field) => field switch
    {
        "CustomerName" => _customer,
        "ProductName" => _product,
        "Quantity" => _quantity,
        "UnitPrice" => _unitPrice,
        _ => null
    };

    private static void AddField(TableLayoutPanel layout, int row, string text, string name, Control field, int tabIndex)
    {
        layout.Controls.Add(CreateLabel(text, name), 0, row);
        field.TabIndex = tabIndex;
        layout.Controls.Add(field, 1, row);
    }

    private static Label CreateLabel(string text, string name) => new()
    {
        Name = name,
        AccessibleName = text,
        Text = text,
        AutoSize = true,
        Anchor = AnchorStyles.Left,
        Margin = new Padding(3, 9, 3, 9)
    };

    private static Label CreateStatusLabel(string name, string accessibleName) => new()
    {
        Name = name,
        AccessibleName = accessibleName,
        AutoSize = true,
        Dock = DockStyle.Fill,
        Margin = new Padding(3, 10, 3, 10)
    };

    private static void SetStatus(Label label, string text)
    {
        label.Text = text;
        label.AccessibleName = string.IsNullOrEmpty(text) ? label.Name : text;
    }

    private static TextBox CreateTextBox(string name, string accessibleName, bool readOnly = false) => new()
    {
        Name = name,
        AccessibleName = accessibleName,
        ReadOnly = readOnly,
        Dock = DockStyle.Fill,
        MaxLength = readOnly ? 32767 : 100
    };

    private static Button CreateButton(string name, string text, int tabIndex) => new()
    {
        Name = name,
        AccessibleName = text,
        Text = text,
        AutoSize = true,
        TabIndex = tabIndex
    };
}
