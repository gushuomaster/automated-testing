namespace MiniOrder.Core;

public sealed class OrderService(
    IOrderRepository repository,
    OrderValidator validator,
    OrderAmountCalculator amountCalculator,
    Func<DateTimeOffset>? now = null)
{
    private readonly Func<DateTimeOffset> _now = now ?? (() => DateTimeOffset.Now);

    public OrderCreationResult Create(OrderDraft draft)
    {
        var validation = validator.Validate(draft);
        if (!validation.IsValid)
        {
            return new OrderCreationResult(null, validation.Issues);
        }

        var input = validation.Value!;
        var existingOrders = repository.Load().ToList();
        var createdAt = _now();
        var order = new Order(
            OrderNumberGenerator.Generate(DateOnly.FromDateTime(createdAt.LocalDateTime), existingOrders),
            input.CustomerName,
            input.ProductName,
            input.Quantity,
            input.UnitPrice,
            amountCalculator.Calculate(input.Quantity, input.UnitPrice),
            ProductInfo.NewStatus,
            createdAt);

        existingOrders.Add(order);
        repository.Save(existingOrders);
        return new OrderCreationResult(order, Array.Empty<ValidationIssue>());
    }

    public IReadOnlyList<Order> Query(string? keyword = null, string? status = null)
    {
        var normalizedKeyword = keyword?.Trim() ?? string.Empty;
        var normalizedStatus = status?.Trim() ?? string.Empty;

        return repository.Load()
            .Where(order => normalizedKeyword.Length == 0 ||
                order.OrderNumber.Contains(normalizedKeyword, StringComparison.OrdinalIgnoreCase) ||
                order.CustomerName.Contains(normalizedKeyword, StringComparison.OrdinalIgnoreCase) ||
                order.ProductName.Contains(normalizedKeyword, StringComparison.OrdinalIgnoreCase))
            .Where(order => normalizedStatus.Length == 0 ||
                string.Equals(order.Status, normalizedStatus, StringComparison.Ordinal))
            .OrderByDescending(order => order.CreatedAt)
            .ThenByDescending(order => order.OrderNumber, StringComparer.Ordinal)
            .ToArray();
    }
}
