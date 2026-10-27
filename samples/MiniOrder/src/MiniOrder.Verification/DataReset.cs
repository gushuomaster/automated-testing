namespace MiniOrder.Verification;

internal static class DataReset
{
    public static string Reset(string seedPath, string targetDirectory)
    {
        var source = Path.GetFullPath(seedPath);
        var targetDirectoryPath = Path.GetFullPath(targetDirectory);
        if (!File.Exists(source))
        {
            throw new FileNotFoundException("找不到种子数据文件。", source);
        }

        Directory.CreateDirectory(targetDirectoryPath);
        var target = Path.Combine(targetDirectoryPath, "orders.json");
        var temporary = Path.Combine(targetDirectoryPath, $".orders.reset.{Guid.NewGuid():N}.tmp");
        try
        {
            File.Copy(source, temporary, overwrite: false);
            if (File.Exists(target))
            {
                File.Replace(temporary, target, destinationBackupFileName: null);
            }
            else
            {
                File.Move(temporary, target);
            }
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }

        return Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(target)));
    }
}
