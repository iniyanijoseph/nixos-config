{ pkgs, ... }:
{
  # Manage Thunderbird itself through Home Manager so its add-on policy is
  # reproducible too. Provider for Google Calendar 128.5.12 fixes the repeated
  # Google OAuth prompt seen with Thunderbird 152 / provider 128.5.11.
  programs.thunderbird = {
    enable = true;
    policies.ExtensionSettings."{a62ef8ec-5fdc-40c2-873c-223b8a6925cc}" = {
      installation_mode = "normal_installed";
      install_url = "https://addons.thunderbird.net/thunderbird/downloads/file/1048156/provider_for_google_calendar-128.5.12-tb.xpi";
      updates_disabled = false;
    };
  };

  home.packages = with pkgs; [
    # element-desktop
    cinny-desktop
  ];
}
