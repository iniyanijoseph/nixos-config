{ ... }:
{
  # Manage Thunderbird through Home Manager so its add-on policy is
  # reproducible. Keep the Provider for Google Calendar version that fixes
  # repeated Google OAuth prompts.
  programs.thunderbird = {
    enable = true;
    policies.ExtensionSettings."{a62ef8ec-5fdc-40c2-873c-223b8a6925cc}" = {
      installation_mode = "normal_installed";
      install_url = "https://addons.thunderbird.net/thunderbird/downloads/file/1048156/provider_for_google_calendar-128.5.12-tb.xpi";
      updates_disabled = false;
    };
  };
}
