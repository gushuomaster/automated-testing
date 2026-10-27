using MiniOrder.Core;

namespace MiniOrder.App;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        try
        {
            var dataDirectory = CommandLineOptions.ResolveDataDirectory(Environment.GetCommandLineArgs().Skip(1).ToArray());
            var behavior = BehaviorFactory.Create();
            var repository = new JsonOrderRepository(dataDirectory);
            var validator = new OrderValidator(behavior);
            var service = new OrderService(repository, validator, new OrderAmountCalculator(behavior));
            Application.Run(new MainForm(service, validator, new OrderAmountCalculator(behavior)));
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, ProductInfo.Name, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}

internal static class CommandLineOptions
{
    public static string ResolveDataDirectory(string[] args)
    {
        for (var index = 0; index < args.Length; index++)
        {
            if (string.Equals(args[index], "--data-dir", StringComparison.OrdinalIgnoreCase))
            {
                if (index + 1 >= args.Length || string.IsNullOrWhiteSpace(args[index + 1]))
                {
                    throw new ArgumentException("--data-dir 必须指定目录。", nameof(args));
                }

                return Path.GetFullPath(args[index + 1]);
            }
        }

        return Path.Combine(AppContext.BaseDirectory, "data");
    }
}
