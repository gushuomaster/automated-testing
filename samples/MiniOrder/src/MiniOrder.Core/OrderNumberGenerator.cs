using System.Globalization;

namespace MiniOrder.Core;

public static class OrderNumberGenerator
{
    public static string Generate(DateOnly localDate, IEnumerable<Order> existingOrders)
    {
        ArgumentNullException.ThrowIfNull(existingOrders);

        var prefix = $"MO-{localDate:yyyyMMdd}-";
        var maximumSequence = existingOrders
            .Select(order => order.OrderNumber)
            .Where(number => number.StartsWith(prefix, StringComparison.Ordinal))
            .Select(number => int.TryParse(number.AsSpan(prefix.Length), NumberStyles.None, CultureInfo.InvariantCulture, out var sequence)
                ? sequence
                : 0)
            .DefaultIfEmpty(0)
            .Max();

        if (maximumSequence >= 9999)
        {
            throw new InvalidOperationException("当天订单流水号已用尽。");
        }

        return $"{prefix}{maximumSequence + 1:0000}";
    }
}
