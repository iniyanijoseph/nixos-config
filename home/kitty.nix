{ ... }:
{
  programs.kitty = {
    enable = true;

    themeFile = "gruvbox-dark-hard";

    font = {
      name = "Maple Mono";
      size = 12;
    };

    extraConfig = ''
      font_features MapleMono-Regular +ss01 +ss02 +ss04
      font_features MapleMono-Bold +ss01 +ss02 +ss04
      font_features MapleMono-Italic +ss01 +ss02 +ss04
      font_features MapleMono-Light +ss01 +ss02 +ss04
    '';

    settings = {
      confirm_os_window_close = 0;
      background_opacity = "0.66";
      scrollback_lines = 10000;
      enable_audio_bell = false;
      mouse_hide_wait = 60;
      window_padding_width = 5;
      # Hyprland owns OS-window geometry. If this is enabled, Kitty also
      # remembers the previous maximize state, which can make a new terminal
      # request a maximized window instead of entering the tiling layout normally.
      remember_window_size = false;
      initial_window_width = "120c";
      initial_window_height = "34c";

      # Side-by-side terminal windows. Alt+A turns the current Kitty tab into
      # a lightweight Helix + Codex IDE.
      enabled_layouts = "splits:split_axis=horizontal";

      ## Tabs
      tab_title_template = "{index}";
      active_tab_font_style = "normal";
      inactive_tab_font_style = "normal";
      tab_bar_style = "powerline";
      tab_powerline_style = "angled";
      active_tab_foreground = "#FBF1C7";
      active_tab_background = "#7C6F64";
      inactive_tab_foreground = "#FBF1C7";
      inactive_tab_background = "#3C3836";
    };

    keybindings = {
      ## Tabs
      "alt+1" = "goto_tab 1";
      "alt+2" = "goto_tab 2";
      "alt+3" = "goto_tab 3";
      "alt+4" = "goto_tab 4";

      ## Helix + Codex
      # Open Codex on the right in the same working directory, using about
      # 38% of the tab width.
      "alt+a" = "launch --location=vsplit --bias=38 --cwd=current codex";

      # Move between editor and agent.
      "alt+left" = "neighboring_window left";
      "alt+right" = "neighboring_window right";
      "alt+l" = "neighboring_window left";
      "alt+h" = "neighboring_window right";
      "alt+k" = "neighboring_window up";
      "alt+j" = "neighboring_window down";

      # Resize the focused side of the split.
      "alt+shift+left" = "resize_window narrower";
      "alt+shift+right" = "resize_window wider";
      "alt+shift+l" = "resize_window narrower";
      "alt+shift+h" = "resize_window wider";

      ## Unbind
      "ctrl+shift+left" = "no_op";
      "ctrl+shift+right" = "no_op";
    };
  };
}
