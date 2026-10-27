namespace MiniOrder.Core;

public static class BehaviorFactory
{
    public static IOrderBehavior Create()
    {
#if MINIORDER_VARIANT_A
        return new QuantityZeroOrderBehavior();
#elif MINIORDER_VARIANT_B
        return new AdditiveAmountOrderBehavior();
#else
        return new BaselineOrderBehavior();
#endif
    }

    private sealed class QuantityZeroOrderBehavior : IOrderBehavior
    {
        public bool IsQuantityInRange(int quantity) => quantity is >= 0 and <= 999;

        public decimal CalculateAmount(int quantity, decimal unitPrice) => quantity * unitPrice;
    }

    private sealed class AdditiveAmountOrderBehavior : IOrderBehavior
    {
        public bool IsQuantityInRange(int quantity) => quantity is >= 1 and <= 999;

        public decimal CalculateAmount(int quantity, decimal unitPrice) => quantity + unitPrice;
    }
}
