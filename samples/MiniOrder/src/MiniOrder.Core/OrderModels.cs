namespace MiniOrder.Core;

public sealed record OrderDraft(string CustomerName, string ProductName, string Quantity, string UnitPrice);

public sealed record Order(
    string OrderNumber,
    string CustomerName,
    string ProductName,
    int Quantity,
    decimal UnitPrice,
    decimal Amount,
    string Status,
    DateTimeOffset CreatedAt);

public sealed record ValidatedOrderInput(string CustomerName, string ProductName, int Quantity, decimal UnitPrice);

public sealed record ValidationIssue(string Field, string Message);

public sealed record OrderValidationResult(ValidatedOrderInput? Value, IReadOnlyList<ValidationIssue> Issues)
{
    public bool IsValid => Value is not null && Issues.Count == 0;
}

public sealed record OrderCreationResult(Order? Order, IReadOnlyList<ValidationIssue> Issues)
{
    public bool IsSuccess => Order is not null && Issues.Count == 0;
}
