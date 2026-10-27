using System.Text.Json;
using System.Text.Json.Serialization;

namespace MiniOrder.Core;

public sealed class JsonOrderRepository
    : IOrderRepository
{
    public const int CurrentSchemaVersion = 1;
    public const string DataFileName = "orders.json";

    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never
    };

    private readonly string _dataFilePath;

    public JsonOrderRepository(string dataDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(dataDirectory);
        _dataFilePath = Path.Combine(Path.GetFullPath(dataDirectory), DataFileName);
    }

    public IReadOnlyList<Order> Load()
    {
        if (!File.Exists(_dataFilePath))
        {
            return Array.Empty<Order>();
        }

        try
        {
            using var stream = new FileStream(_dataFilePath, FileMode.Open, FileAccess.Read, FileShare.Read);
            var document = JsonSerializer.Deserialize<OrderDataDocument>(stream, SerializerOptions);
            ValidateDocument(document);
            return document!.Orders.ToArray();
        }
        catch (InvalidDataException)
        {
            throw;
        }
        catch (Exception exception) when (exception is JsonException or IOException or UnauthorizedAccessException)
        {
            throw new InvalidDataException("订单数据文件无法读取或格式无效。", exception);
        }
    }

    public void Save(IReadOnlyList<Order> orders)
    {
        ArgumentNullException.ThrowIfNull(orders);
        ValidateOrders(orders);

        var directory = Path.GetDirectoryName(_dataFilePath)!;
        Directory.CreateDirectory(directory);
        var temporaryPath = Path.Combine(directory, $".{DataFileName}.{Guid.NewGuid():N}.tmp");

        try
        {
            using (var stream = new FileStream(
                temporaryPath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                bufferSize: 4096,
                FileOptions.WriteThrough))
            {
                JsonSerializer.Serialize(stream, new OrderDataDocument(CurrentSchemaVersion, orders.ToArray()), SerializerOptions);
                stream.Flush(flushToDisk: true);
            }

            if (File.Exists(_dataFilePath))
            {
                File.Replace(temporaryPath, _dataFilePath, destinationBackupFileName: null);
            }
            else
            {
                File.Move(temporaryPath, _dataFilePath);
            }
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }

    private static void ValidateDocument(OrderDataDocument? document)
    {
        if (document is null || document.SchemaVersion != CurrentSchemaVersion || document.Orders is null)
        {
            throw new InvalidDataException($"订单数据 schema 必须为版本 {CurrentSchemaVersion}。");
        }

        ValidateOrders(document.Orders);
    }

    private static void ValidateOrders(IReadOnlyList<Order> orders)
    {
        if (orders.Any(order =>
            string.IsNullOrWhiteSpace(order.OrderNumber) ||
            string.IsNullOrWhiteSpace(order.CustomerName) ||
            string.IsNullOrWhiteSpace(order.ProductName) ||
            string.IsNullOrWhiteSpace(order.Status)))
        {
            throw new InvalidDataException("订单数据包含缺少必填字段的记录。");
        }

        if (orders.Select(order => order.OrderNumber).Distinct(StringComparer.Ordinal).Count() != orders.Count)
        {
            throw new InvalidDataException("订单数据包含重复订单编号。");
        }
    }

    private sealed record OrderDataDocument(int SchemaVersion, Order[] Orders);
}
