using System.Globalization;

namespace MiniOrder.Core;

public interface IOrderBehavior
{
    bool IsQuantityInRange(int quantity);

    decimal CalculateAmount(int quantity, decimal unitPrice);
}

public sealed class BaselineOrderBehavior : IOrderBehavior
{
    public bool IsQuantityInRange(int quantity) => quantity is >= 1 and <= 999;

    public decimal CalculateAmount(int quantity, decimal unitPrice) => quantity * unitPrice;
}

public sealed class OrderValidator(IOrderBehavior behavior)
{
    public const int MaximumTextLength = 50;
    public const decimal MinimumUnitPrice = 0.01m;
    public const decimal MaximumUnitPrice = 999999.99m;

    public OrderValidationResult Validate(OrderDraft draft)
    {
        ArgumentNullException.ThrowIfNull(draft);

        var issues = new List<ValidationIssue>();
        var customerName = ValidateText("CustomerName", "客户名称", draft.CustomerName, issues);
        var productName = ValidateText("ProductName", "商品名称", draft.ProductName, issues);
        var quantity = ValidateQuantity(draft.Quantity, issues);
        var unitPrice = ValidateUnitPrice(draft.UnitPrice, issues);

        if (issues.Count > 0 || quantity is null || unitPrice is null)
        {
            return new OrderValidationResult(null, issues);
        }

        return new OrderValidationResult(
            new ValidatedOrderInput(customerName!, productName!, quantity.Value, unitPrice.Value),
            issues);
    }

    private static string? ValidateText(
        string field,
        string displayName,
        string? value,
        ICollection<ValidationIssue> issues)
    {
        var trimmed = value?.Trim() ?? string.Empty;
        if (trimmed.Length == 0)
        {
            issues.Add(new ValidationIssue(field, $"{displayName}不能为空。"));
            return null;
        }

        if (trimmed.Length > MaximumTextLength)
        {
            issues.Add(new ValidationIssue(field, $"{displayName}不能超过 {MaximumTextLength} 个字符。"));
            return null;
        }

        return trimmed;
    }

    private int? ValidateQuantity(string? value, ICollection<ValidationIssue> issues)
    {
        if (!int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var quantity))
        {
            issues.Add(new ValidationIssue("Quantity", "数量必须是整数。"));
            return null;
        }

        if (!behavior.IsQuantityInRange(quantity))
        {
            issues.Add(new ValidationIssue("Quantity", "数量必须在 1～999 之间。"));
            return null;
        }

        return quantity;
    }

    private static decimal? ValidateUnitPrice(string? value, ICollection<ValidationIssue> issues)
    {
        const NumberStyles styles = NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint;
        if (!decimal.TryParse(value, styles, CultureInfo.InvariantCulture, out var unitPrice))
        {
            issues.Add(new ValidationIssue("UnitPrice", "单价必须是最多包含两位小数的数字。"));
            return null;
        }

        var scale = (decimal.GetBits(unitPrice)[3] >> 16) & 0x7F;
        if (scale > 2)
        {
            issues.Add(new ValidationIssue("UnitPrice", "单价最多保留两位小数。"));
            return null;
        }

        if (unitPrice is < MinimumUnitPrice or > MaximumUnitPrice)
        {
            issues.Add(new ValidationIssue(
                "UnitPrice",
                $"单价必须在 {MinimumUnitPrice:F2}～{MaximumUnitPrice:F2} 之间。"));
            return null;
        }

        return unitPrice;
    }
}

public sealed class OrderAmountCalculator(IOrderBehavior behavior)
{
    public decimal Calculate(int quantity, decimal unitPrice) =>
        decimal.Round(behavior.CalculateAmount(quantity, unitPrice), 2, MidpointRounding.AwayFromZero);
}
