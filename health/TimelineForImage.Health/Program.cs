using System.Text;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://0.0.0.0:8080");

var app = builder.Build();

app.MapGet("/health", () => Results.Json(IsHealthy()));

app.Run();

static bool IsHealthy()
{
    try
    {
        var stateRoot = Environment.GetEnvironmentVariable("TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT");
        if (string.IsNullOrWhiteSpace(stateRoot))
        {
            stateRoot = "/shared/app-data/timeline-for-image-state";
        }

        Directory.CreateDirectory(stateRoot);
        var probe = Path.Combine(stateRoot, $".health-{Environment.ProcessId}.tmp");
        File.WriteAllText(probe, "ok", Encoding.UTF8);
        File.Delete(probe);
        return true;
    }
    catch
    {
        return false;
    }
}
