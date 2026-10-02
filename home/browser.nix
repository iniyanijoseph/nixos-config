{ inputs, pkgs, ... }:
let
  surfingkeysConfig = ./surfingkeys.js;
  surfingkeysConfigDir = pkgs.runCommand "surfingkeys-files" { } ''
    mkdir -p "$out"
    cp ${surfingkeysConfig} "$out/surfingkeys.js"
  '';

  # Install from AMO without pinning a version. Firefox's ExtensionSettings
  # policy follows the latest compatible XPI and leaves automatic updates on.
  amoExtension = slug: extra:
    {
      installation_mode = "normal_installed";
      install_url = "https://addons.mozilla.org/firefox/downloads/latest/${slug}/latest.xpi";
      updates_disabled = false;
    }
    // extra;
in
{
  programs.qutebrowser = {
    enable = true;
    keyBindings.normal = {
      # Match the user's Helix direction map while leaving arrow keys intact.
      "h" = "scroll right";
      "l" = "scroll left";
      "j" = "scroll down";
      "k" = "scroll up";
      "?" = "open qute://help/";
    };
  };

  programs.firefox = {
    enable = true;
    # Reproduce the user's extension set, but do not pin extension versions.
    # normal_installed keeps the extensions declarative while still allowing
    # them to be disabled by the user; updates remain enabled explicitly.
    policies.ExtensionSettings = {
      # Tabby Cat update for Firefox
      "{c6a558cf-709d-4ec0-8a56-0563ca46b403}" =
        amoExtension "tabby-cat-update-for-firefox" {
          default_area = "menupanel";
        };

      # HTTPS Everywhere Lite+
      "{0e7050a5-72b2-4157-95a3-56d0b51626bc}" =
        amoExtension "https-everywhere-lite" {
          default_area = "menupanel";
        };

      # Google Scholar Button
      "button@scholar.google.com" =
        amoExtension "google-scholar-button" {
          default_area = "navbar";
        };

      # Privacy Possum
      "woop-NoopscooPsnSXQ@jetpack" =
        amoExtension "privacy-possum" {
          default_area = "menupanel";
        };

      # Surfingkeys; its actual key configuration is managed below from
      # home/surfingkeys.js.
      "{a8332c60-5b6d-41ee-bfc8-e9bb331d34ad}" =
        amoExtension "surfingkeys_ff" {
          default_area = "menupanel";
        };

      # Copy LaTeX
      "copy-latex@mapaor" =
        amoExtension "copy-latex" {
          default_area = "menupanel";
        };

      # DuckDuckGo Search & Tracker Protection
      "jid1-ZAdIEUB7XOzOJw@jetpack" =
        amoExtension "duckduckgo-for-firefox" {
          default_area = "menupanel";
        };

      # Skip Redirect
      "skipredirect@sblask" =
        amoExtension "skip-redirect" {
          default_area = "navbar";
          private_browsing = true;
        };

      # WebHID for Firefox
      "{8badf7fe-c0e0-464b-a329-1411c3b3651a}" =
        amoExtension "webhid-for-firefox" {
          default_area = "menupanel";
        };

      # FxQRL
      "jid1-DNc5AXAyVmgNjQ@jetpack" =
        amoExtension "fxqrl" {
          default_area = "navbar";
          private_browsing = true;
        };

      # uBlock Origin
      "uBlock0@raymondhill.net" =
        amoExtension "ublock-origin" {
          default_area = "navbar";
          private_browsing = true;
        };

      # Dark Reader
      "addon@darkreader.org" =
        amoExtension "darkreader" {
          default_area = "menupanel";
        };

      # Focus Blank Break is the user's own AMO-signed extension. Keep its
      # current signed XPI as the bootstrap URL and leave updates enabled.
      # Its runtime preferences are handled separately from installation.
      "focus-blank-break@example.com" = {
        installation_mode = "normal_installed";
        install_url = "https://addons.mozilla.org/firefox/downloads/file/5067415/distraction_affliction_correct-1.6.xpi";
        updates_disabled = false;
        default_area = "navbar";
        private_browsing = true;
      };

      # Zotero distributes its Firefox connector directly rather than via AMO.
      # The installed connector carries Zotero's own update URL.
      "zotero@chnm.gmu.edu" = {
        installation_mode = "normal_installed";
        install_url = "https://download.zotero.org/connector/firefox/release/Zotero_Connector-5.0.217.xpi";
        updates_disabled = false;
        default_area = "navbar";
        private_browsing = true;
      };

      # Explicitly remove the old managed New Tab Override extension.
      "newtaboverride@agenedia.com" = {
        installation_mode = "blocked";
      };
    };

    # uBlock Origin supports Firefox managed storage directly. These are the
    # user-added trusted sites present in the exported profile; toAdd preserves
    # uBO's built-in directives and any future local directives.
    policies."3rdparty".Extensions."uBlock0@raymondhill.net" = {
      toAdd.trustedSiteDirectives = [
        "chatgpt.com"
        "purdueteamstore.com"
        "slack.com"
      ];
    };


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
        # Use the XDG file-picker portal, which is backed by Yazi in files.nix.
        "widget.use-xdg-desktop-portal.file-picker" = 1;

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

  # Keep a normal local copy for editing/reference.
  home.file.".surfingkeys.js".source = surfingkeysConfig;

  # The currently released Firefox add-on cannot read local files directly.
  # Serve only the generated Surfingkeys config on loopback; Surfingkeys can
  # load ordinary http(s) URLs on every page load.
  systemd.user.services.surfingkeys-config = {
    Unit = {
      Description = "Serve Surfingkeys configuration";
      After = [ "network.target" ];
    };
    Service = {
      ExecStart = "${pkgs.python3}/bin/python -m http.server 8765 --bind 127.0.0.1 --directory ${surfingkeysConfigDir}";
      Restart = "on-failure";
    };
    Install.WantedBy = [ "default.target" ];
  };

  home.packages = [
    pkgs.openconnect
  ];
}
