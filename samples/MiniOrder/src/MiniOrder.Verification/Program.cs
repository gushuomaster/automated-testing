using MiniOrder.Core;
using MiniOrder.App;
using MiniOrder.Verification;
using System.Reflection;

return VerificationProgram.Run(args);

internal static class VerificationProgram
{
    public static int Run(string[] args)
    {
        var command = args.FirstOrDefault() ?? "core";
        var suite = new VerificationSuite();
        switch (command.ToLowerInvariant())
        {
            case "core":
                suite.RunCoreContracts();
                break;
            case "persistence":
                suite.RunPersistenceContracts(GetWorkDirectory(args));
                break;
            case "matrix":
                suite.RunVariantMatrix();
                break;
            case "reset":
                if (args.Length != 3)
                {
                    Console.Error.WriteLine("用法：reset <seed-file> <data-directory>");
                    return 2;
                }
                Console.WriteLine($"RESET SHA256={DataReset.Reset(args[1], args[2])}");
                break;
            case "reset-check":
                if (args.Length != 3)
                {
                    Console.Error.WriteLine("用法：reset-check <seed-file> <data-directory>");
                    return 2;
                }
                suite.RunResetContracts(args[1], args[2]);
                break;
            case "accept-button":
                suite.RunAcceptButtonContracts(GetWorkDirectory(args));
                break;
            default:
                Console.Error.WriteLine($"未知命令：{command}");
                return 2;
        }

        return suite.Complete();
    }

    private static string GetWorkDirectory(string[] args)
    {
        var requested = args.Skip(1).FirstOrDefault();
        return Path.GetFullPath(requested ?? Path.Combine(
            "artifacts",
            "miniorder",
            "diagnostics",
            "verification",
            "persistence"));
    }
}

internal sealed class VerificationSuite
{
    private int _passed;
    private int _failed;

    public void RunCoreContracts()
    {
        var behavior = new BaselineOrderBehavior();
        var validator = new OrderValidator(behavior);
        var calculator = new OrderAmountCalculator(behavior);

        Check("有效输入通过并去除首尾空白", () =>
        {
            var result = validator.Validate(new OrderDraft("  客户甲  ", " 商品甲 ", "1", "0.01"));
            Equal(true, result.IsValid);
            Equal("客户甲", result.Value?.CustomerName);
            Equal("商品甲", result.Value?.ProductName);
        });

        Invalid(validator, "客户名称为空", new(" ", "商品", "1", "1.00"), "CustomerName");
        Invalid(validator, "商品名称为空", new("客户", " ", "1", "1.00"), "ProductName");
        Invalid(validator, "客户名称超过 50 字符", new(new string('甲', 51), "商品", "1", "1.00"), "CustomerName");
        Invalid(validator, "商品名称超过 50 字符", new("客户", new string('乙', 51), "1", "1.00"), "ProductName");
        Valid(validator, "数量下边界", new("客户", "商品", "1", "1.00"));
        Valid(validator, "数量上边界", new("客户", "商品", "999", "1.00"));
        Invalid(validator, "数量为零", new("客户", "商品", "0", "1.00"), "Quantity");
        Invalid(validator, "数量为负", new("客户", "商品", "-1", "1.00"), "Quantity");
        Invalid(validator, "数量超过上界", new("客户", "商品", "1000", "1.00"), "Quantity");
        Invalid(validator, "数量为小数", new("客户", "商品", "1.5", "1.00"), "Quantity");
        Invalid(validator, "数量不是数字", new("客户", "商品", "abc", "1.00"), "Quantity");
        Valid(validator, "单价下边界", new("客户", "商品", "1", "0.01"));
        Valid(validator, "单价上边界", new("客户", "商品", "1", "999999.99"));
        Invalid(validator, "单价为零", new("客户", "商品", "1", "0"), "UnitPrice");
        Invalid(validator, "单价超过上界", new("客户", "商品", "1", "1000000.00"), "UnitPrice");
        Invalid(validator, "单价超过两位小数", new("客户", "商品", "1", "1.001"), "UnitPrice");
        Invalid(validator, "单价不是数字", new("客户", "商品", "1", "abc"), "UnitPrice");
        Check("金额使用十进制乘法", () => Equal(37.50m, calculator.Calculate(3, 12.50m)));

        Check("订单编号按日期和最大流水递增", () =>
        {
            var date = new DateOnly(2026, 10, 21);
            var existing = new[]
            {
                SampleOrder("MO-20261021-0001", "客户甲"),
                SampleOrder("MO-20261021-0003", "客户乙"),
                SampleOrder("MO-20261020-0099", "客户丙")
            };
            Equal("MO-20261021-0004", OrderNumberGenerator.Generate(date, existing));
        });

        Check("有效订单只保存一次并可查询", () =>
        {
            var repository = new MemoryRepository();
            var service = new OrderService(
                repository,
                validator,
                calculator,
                () => new DateTimeOffset(2026, 10, 21, 9, 30, 0, TimeSpan.FromHours(8)));
            var result = service.Create(new OrderDraft("Alpha 客户", "Widget", "3", "12.50"));
            Equal(true, result.IsSuccess);
            Equal(1, repository.Load().Count);
            Equal("MO-20261021-0001", result.Order?.OrderNumber);
            Equal(ProductInfo.NewStatus, result.Order?.Status);
            Equal(1, service.Query("alpha", ProductInfo.NewStatus).Count);
            Equal(0, service.Query("missing", null).Count);
        });

        Check("无效订单不会保存", () =>
        {
            var repository = new MemoryRepository();
            var service = new OrderService(repository, validator, calculator);
            var result = service.Create(new OrderDraft("", "商品", "1", "1.00"));
            Equal(false, result.IsSuccess);
            Equal(0, repository.Load().Count);
            Equal(0, repository.SaveCount);
        });
    }

    public void RunPersistenceContracts(string workDirectory)
    {
        if (Directory.Exists(workDirectory))
        {
            Directory.Delete(workDirectory, recursive: true);
        }

        Directory.CreateDirectory(workDirectory);
        Check("JSON 保存和重新加载往返一致", () =>
        {
            var dataDirectory = Path.Combine(workDirectory, "round-trip");
            var repository = new JsonOrderRepository(dataDirectory);
            var expected = new[] { SampleOrder("MO-20261021-0001", "客户甲") };
            repository.Save(expected);
            var actual = repository.Load();
            Equal(1, actual.Count);
            Equal(expected[0], actual[0]);
            Equal(true, File.ReadAllText(Path.Combine(dataDirectory, JsonOrderRepository.DataFileName))
                .Contains("\"schemaVersion\": 1", StringComparison.Ordinal));
            Equal(0, Directory.GetFiles(dataDirectory, "*.tmp").Length);
        });

        Check("损坏 JSON 明确失败", () =>
        {
            var dataDirectory = Path.Combine(workDirectory, "corrupt-json");
            Directory.CreateDirectory(dataDirectory);
            File.WriteAllText(Path.Combine(dataDirectory, JsonOrderRepository.DataFileName), "{not-json");
            Throws<InvalidDataException>(() => new JsonOrderRepository(dataDirectory).Load());
        });

        Check("未知 schema 明确失败", () =>
        {
            var dataDirectory = Path.Combine(workDirectory, "wrong-schema");
            Directory.CreateDirectory(dataDirectory);
            File.WriteAllText(
                Path.Combine(dataDirectory, JsonOrderRepository.DataFileName),
                "{\"schemaVersion\":999,\"orders\":[]}");
            Throws<InvalidDataException>(() => new JsonOrderRepository(dataDirectory).Load());
        });

        Check("不同数据目录相互隔离", () =>
        {
            var first = new JsonOrderRepository(Path.Combine(workDirectory, "isolated-a"));
            var second = new JsonOrderRepository(Path.Combine(workDirectory, "isolated-b"));
            first.Save(new[] { SampleOrder("MO-20261021-0001", "仅目录 A") });
            Equal(1, first.Load().Count);
            Equal(0, second.Load().Count);
        });
    }

    public void RunVariantMatrix()
    {
        Check("当前变体只产生预期契约差异", () =>
        {
            var behavior = BehaviorFactory.Create();
            var validator = new OrderValidator(behavior);
            var calculator = new OrderAmountCalculator(behavior);
            var violations = new List<string>();

            if (validator.Validate(new OrderDraft("客户", "商品", "0", "12.50")).IsValid)
            {
                violations.Add("quantity-zero-rejected");
            }

            if (calculator.Calculate(3, 12.50m) != 37.50m)
            {
                violations.Add("amount-uses-multiplication");
            }

            var unaffectedInputsAreValid =
                validator.Validate(new OrderDraft("客户", "商品", "1", "0.01")).IsValid &&
                validator.Validate(new OrderDraft("客户", "商品", "999", "999999.99")).IsValid;
            if (!unaffectedInputsAreValid)
            {
                violations.Add("unrelated-valid-boundaries");
            }

            var expected = CurrentVariantName() switch
            {
                "Baseline" => Array.Empty<string>(),
                "VariantA" => new[] { "quantity-zero-rejected" },
                "VariantB" => new[] { "amount-uses-multiplication" },
                _ => throw new InvalidOperationException("未知编译变体。")
            };

            Equal(string.Join(",", expected), string.Join(",", violations));
            Console.WriteLine($"MATRIX {CurrentVariantName()}: violations=[{string.Join(",", violations)}]");
        });
    }

    public void RunResetContracts(string seedPath, string dataDirectory)
    {
        Check("连续重置哈希相同并清除新增订单", () =>
        {
            var firstHash = DataReset.Reset(seedPath, dataDirectory);
            var repository = new JsonOrderRepository(dataDirectory);
            var orders = repository.Load().ToList();
            orders.Add(SampleOrder("MO-20261021-9999", "实验新增客户"));
            repository.Save(orders);
            Equal(3, repository.Load().Count);

            var secondHash = DataReset.Reset(seedPath, dataDirectory);
            Equal(firstHash, secondHash);
            Equal(2, repository.Load().Count);
            Equal(false, repository.Load().Any(order => order.CustomerName == "实验新增客户"));
            Console.WriteLine($"RESET SHA256={secondHash}");
        });
    }

    public void RunAcceptButtonContracts(string workDirectory)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                RunAcceptButtonContractsOnSta(workDirectory);
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (failure is not null)
        {
            throw new InvalidOperationException("默认按钮合约失败。", failure);
        }
    }

    private void RunAcceptButtonContractsOnSta(string workDirectory)
    {
        if (Directory.Exists(workDirectory))
        {
            Directory.Delete(workDirectory, recursive: true);
        }
        Directory.CreateDirectory(workDirectory);

        var behavior = BehaviorFactory.Create();
        var repository = new JsonOrderRepository(workDirectory);
        var validator = new OrderValidator(behavior);
        using var form = new MainForm(
            new OrderService(
                repository,
                validator,
                new OrderAmountCalculator(behavior),
                () => new DateTimeOffset(2026, 10, 21, 9, 30, 0, TimeSpan.FromHours(8))),
            validator,
            new OrderAmountCalculator(behavior))
        {
            ShowInTaskbar = false,
            StartPosition = FormStartPosition.Manual,
            Location = new Point(-32000, -32000)
        };
        form.Show();
        Application.DoEvents();

        var tabs = FindControl<TabControl>(form, "MainTabs");
        Check("新建订单页 Enter 默认触发保存", () =>
        {
            Equal("SaveOrderButton", ((Button)form.AcceptButton!).Name);
            FindControl<TextBox>(form, "CustomerNameInput").Text = "键盘客户";
            FindControl<TextBox>(form, "ProductNameInput").Text = "键盘商品";
            FindControl<TextBox>(form, "QuantityInput").Text = "3";
            var unitPrice = FindControl<TextBox>(form, "UnitPriceInput");
            unitPrice.Text = "12.50";
            unitPrice.Focus();
            Equal(true, ProcessEnter(form));
            Equal(1, repository.Load().Count);
        });

        Check("查询订单页 Enter 默认触发查询", () =>
        {
            tabs.SelectedIndex = 1;
            Application.DoEvents();
            Equal("QueryOrdersButton", ((Button)form.AcceptButton!).Name);
            var keyword = FindControl<TextBox>(form, "QueryKeywordInput");
            keyword.Text = "键盘客户";
            keyword.Focus();
            Equal(true, ProcessEnter(form));
            Equal("找到 1 条订单", FindControl<Label>(form, "QueryResultCount").Text);
        });

        tabs.SelectedIndex = 0;
        Application.DoEvents();
        Check("切回新建页恢复保存默认按钮", () =>
            Equal("SaveOrderButton", ((Button)form.AcceptButton!).Name));
        form.Close();
    }

    private static bool ProcessEnter(Form form)
    {
        var method = typeof(Form).GetMethod("ProcessDialogKey", BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("找不到 WinForms ProcessDialogKey。 ");
        return (bool)(method.Invoke(form, [Keys.Enter]) ?? false);
    }

    private static T FindControl<T>(Control root, string name)
        where T : Control
    {
        return root.Controls.Find(name, searchAllChildren: true).OfType<T>().Single();
    }

    private static string CurrentVariantName()
    {
#if MINIORDER_VARIANT_A
        return "VariantA";
#elif MINIORDER_VARIANT_B
        return "VariantB";
#else
        return "Baseline";
#endif
    }

    public int Complete()
    {
        Console.WriteLine($"验证结果：通过 {_passed}，失败 {_failed}");
        return _failed == 0 ? 0 : 1;
    }

    private void Valid(OrderValidator validator, string name, OrderDraft draft) =>
        Check(name, () => Equal(true, validator.Validate(draft).IsValid));

    private void Invalid(OrderValidator validator, string name, OrderDraft draft, string field) =>
        Check(name, () =>
        {
            var result = validator.Validate(draft);
            Equal(false, result.IsValid);
            Equal(true, result.Issues.Any(issue => issue.Field == field));
        });

    private void Check(string name, Action assertion)
    {
        try
        {
            assertion();
            _passed++;
            Console.WriteLine($"PASS {name}");
        }
        catch (Exception exception)
        {
            _failed++;
            Console.WriteLine($"FAIL {name}: {exception.Message}");
        }
    }

    private static void Equal<T>(T expected, T actual)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
        {
            throw new InvalidOperationException($"期望 {expected}，实际 {actual}。");
        }
    }

    private static void Throws<TException>(Action action)
        where TException : Exception
    {
        try
        {
            action();
        }
        catch (TException)
        {
            return;
        }

        throw new InvalidOperationException($"期望抛出 {typeof(TException).Name}。");
    }

    private static Order SampleOrder(string number, string customer) =>
        new(number, customer, "商品", 1, 1.00m, 1.00m, ProductInfo.NewStatus,
            new DateTimeOffset(2026, 10, 21, 8, 0, 0, TimeSpan.FromHours(8)));

    private sealed class MemoryRepository : IOrderRepository
    {
        private List<Order> _orders = [];

        public int SaveCount { get; private set; }

        public IReadOnlyList<Order> Load() => _orders.ToArray();

        public void Save(IReadOnlyList<Order> orders)
        {
            SaveCount++;
            _orders = orders.ToList();
        }
    }
}
