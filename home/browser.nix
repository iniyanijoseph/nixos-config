{ inputs, pkgs, ... }:
{
  programs.firefox = {
    enable = true;
    # Pin to current behavior explicitly (silences the 26.05 default-change
    # warning - avoids needing to migrate ~/.mozilla/firefox to the XDG path).
    configPath = ".mozilla/firefox";

    # NOTE: home-manager's profile management is keyed on name/id. If you
    # already have a profile at ~/.mozilla/firefox (check `about:profiles`
    # for its exact name/id), set them to match below so this configures
    # your existing profile instead of creating a fresh empty one.
    profiles.default = {
      id = 0;
      isDefault = true;

      # about:config prefs. Goal: make Firefox draw itself with GTK's native
      # widgets wherever possible (so it inherits Colloid-Green-Dark-Gruvbox,
      # Papirus-Dark, Bibata-Modern-Ice automatically like any other GTK app),
      # and hand-color the parts Firefox always draws itself (tabs, toolbar,
      # urlbar) to match the same gruvbox_dark_hard + green palette used in
      # helix.nix/kitty.nix.
      settings = {
        # required for userChrome.css / userContent.css below to load at all
        "toolkit.legacyUserProfileCustomizations.stylesheets" = true;

        # use native GTK theming for form controls, scrollbars, checkboxes,
        # radio buttons, dropdowns, context menus, file pickers - instead of
        # Firefox's own cross-platform "Photon" widgets
        "widget.non-native-theme.enabled" = false;
        "widget.gtk.native-context-menus" = true;

        # force Firefox's built-in dark theme so the parts it always draws
        # itself (toolbar/tab chrome) start from a dark base before
        # userChrome.css repaints them
        "extensions.activeThemeID" = "firefox-compact-dark@mozilla.org";
        "browser.theme.toolbar-theme" = 0; # 0 = dark
        "browser.theme.content-theme" = 0; # 0 = dark
        "browser.theme.dark-private-windows" = true;
        "layout.css.prefers-color-scheme.content-override" = 0; # dark, for sites that respect it

        # flatter chrome, closer to Colloid's rimless/float tweaks
        "browser.tabs.drawInTitlebar" = true;
        "browser.uidensity" = 0;
        "browser.compactmode.show" = true;

        # match gtk.nix's Maple Mono
        "font.name.monospace.x-western" = "Maple Mono";
        "font.name.sans-serif.x-western" = "Maple Mono";
        "font.name.serif.x-western" = "Maple Mono";
        "font.size.monospace.x-western" = 12;
      };

      # Gruvbox Dark Hard palette (same values as kitty.nix's gruvbox-dark-hard
      # theme) with the green accent from Colloid-Green-Dark-Gruvbox.
      userChrome = ''
        :root {
          --gb-bg0-hard: #1d2021;
          --gb-bg0:      #282828;
          --gb-bg1:      #3c3836;
          --gb-bg2:      #504945;
          --gb-fg1:      #ebdbb2;
          --gb-fg0:      #fbf1c7;
          --gb-green:    #b8bb26;
          --gb-aqua:     #8ec07c;

          --toolbar-bgcolor: var(--gb-bg0-hard) !important;
          --toolbar-color: var(--gb-fg1) !important;
          --lwt-accent-color: var(--gb-bg0-hard) !important;
          --lwt-text-color: var(--gb-fg1) !important;
          --toolbarbutton-icon-fill: var(--gb-fg1) !important;
          --urlbar-box-bgcolor: var(--gb-bg0) !important;
          --urlbar-box-focus-bgcolor: var(--gb-bg0) !important;
          --identity-box-label-color: var(--gb-green) !important;
        }

        /* rimless/flat like the Colloid "rimless" tweak */
        #TabsToolbar, #nav-bar {
          background-color: var(--gb-bg0-hard) !important;
          border-bottom: 1px solid var(--gb-bg1) !important;
          box-shadow: none !important;
        }

        /* selected tab gets the green accent underline, like Colloid-Green */
        .tabbrowser-tab[selected] .tab-background {
          background-color: var(--gb-bg1) !important;
          border-bottom: 2px solid var(--gb-green) !important;
        }
        .tabbrowser-tab:not([selected]) .tab-background {
          background-color: var(--gb-bg0-hard) !important;
        }

        #urlbar, #searchbar {
          background-color: var(--gb-bg0) !important;
          color: var(--gb-fg1) !important;
          border: 1px solid var(--gb-bg2) !important;
          border-radius: 4px !important;
        }
        #urlbar[focused] {
          border-color: var(--gb-green) !important;
        }

        :root {
          scrollbar-color: var(--gb-bg2) var(--gb-bg0-hard) !important;
        }
      '';

      # Recolor web content chrome (scrollbars, and about:* pages) to match;
      # actual page content is left alone since sites style themselves.
      userContent = ''
        @-moz-document url(about:blank), url-prefix(about:) {
          :root {
            background-color: #1d2021 !important;
            color: #ebdbb2 !important;
          }
        }
        * {
          scrollbar-color: #504945 #1d2021 !important;
          scrollbar-width: thin !important;
        }
      '';
    };
  };

  home.packages = with pkgs; [ openconnect qutebrowser ];
}
