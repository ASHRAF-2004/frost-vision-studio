# Privacy

Frost Vision Studio 0.2.1 processes your composition locally. It has no
telemetry, sign-in, analytics, advertising, cloud storage or automatic updater.
It does not upload media or hardware readings.

The application stores composition settings, selected media paths, a renderer
lock, local renderer status/control JSON files, and bounded diagnostic logs in:

- Windows: `%LOCALAPPDATA%\FrostVisionStudio`
- Linux: `${XDG_CONFIG_HOME:-~/.config}/aio-screen-manager`

Media stays at the location you select. Choosing login startup creates an
entry for the current user; disabling it removes that entry. The app queries
local CPU/GPU providers where available and communicates with the supported
USB display only when you explicitly start output or enable login startup.

Diagnostics may contain local paths, driver details, platform information and
errors. Review diagnostic files before sharing them in a public issue.
Opening a repository or help link in your browser connects to that website
under its own privacy terms.

Uninstalling preserves settings so that reinstalling does not erase your
composition. To remove them, quit the app, disable login startup, uninstall,
and delete the configuration directory above. This does not delete source media.

GitHub may collect information when you visit releases or submit issues.
Those interactions are separate from the application.
