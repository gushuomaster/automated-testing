namespace MiniOrder.Core;

public interface IOrderRepository
{
    IReadOnlyList<Order> Load();

    void Save(IReadOnlyList<Order> orders);
}
