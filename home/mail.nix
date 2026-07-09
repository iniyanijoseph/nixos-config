{ pkgs, ... }:
{
  # oama handles the OAuth2 device-code dance for both Gmail and Purdue's
  # Office365/Entra tenant and caches the resulting token in the session
  # keyring. aerc just calls `oama access <email>` to get a fresh token.
  home.packages = with pkgs; [ oama pass ];

  # One-time setup after `nixos-rebuild switch`:
  #   oama authorize google iniyanijoseph@gmail.com
  #   oama authorize outlook josep266@purdue.edu
  # (Purdue enforces Duo MFA + conditional access; the browser flow that
  # oama opens will walk you through it. If Purdue's Azure AD blocks the
  # public client below, you'll need to register your own Entra app and
  # swap in its client_id/secret.)
  xdg.configFile."oama/config.yaml".text = ''
    services:
      google:
        # You must create your own OAuth client for Gmail: console.cloud.google.com
        # -> APIs & Services -> Credentials -> OAuth client ID (type "Desktop").
        # Enable the Gmail API and add yourself as a test user, then paste the
        # generated id/secret below.
        client_id: "REPLACE_WITH_YOUR_GOOGLE_CLIENT_ID"
        client_secret: "REPLACE_WITH_YOUR_GOOGLE_CLIENT_SECRET"
      outlook:
        # Public multi-tenant client published by the aerc project for
        # exactly this purpose - not a secret, safe to commit.
        auth_endpoint: "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        token_endpoint: "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        auth_http_method: GET
        token_params_mode: RequestBodyForm
        auth_scope: "https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access"
        client_id: "08162f7c-0fd2-4200-a84a-f25a4db0b584"
        client_secret: "TxRBilcHdC6WGBee]fs?QR:SJ8nI[g82"
        tenant: common
        prompt: select_account
  '';

  accounts.email.accounts = {
    gmail = {
      primary = true;
      address = "iniyanijoseph@gmail.com";
      userName = "iniyanijoseph@gmail.com";
      realName = "Wug";
      flavor = "gmail.com";
      passwordCommand = "oama access iniyanijoseph@gmail.com";
      aerc = {
        enable = true;
        imapAuth = "xoauth2";
        smtpAuth = "xoauth2";
        extraAccounts = {
          source-cred-cmd = "oama access iniyanijoseph@gmail.com";
          outgoing-cred-cmd = "oama access iniyanijoseph@gmail.com";
          copy-to = "[Gmail]/Sent Mail";
          cache-headers = "true";
        };
      };
    };

    purdue = {
      address = "josep266@purdue.edu";
      userName = "josep266@purdue.edu";
      realName = "Wug";
      flavor = "outlook.office365.com";
      passwordCommand = "oama access josep266@purdue.edu";
      aerc = {
        enable = true;
        imapAuth = "xoauth2";
        smtpAuth = "xoauth2";
        extraAccounts = {
          source-cred-cmd = "oama access josep266@purdue.edu";
          outgoing-cred-cmd = "oama access josep266@purdue.edu";
          copy-to = "Sent Items";
          cache-headers = "true";
        };
      };
    };
  };

  programs.aerc = {
    enable = true;
    extraConfig = {
      general = {
        # Home Manager writes accounts.conf into the (world-readable, 0444)
        # nix store, which fails aerc's 0600-permission check. This is safe
        # here because passwordCommand/*-cred-cmd means no secrets are ever
        # written into that file - see aerc-config(5) "unsafe-accounts-conf".
        unsafe-accounts-conf = true;
      };
      ui = {
        sidebar-width = 24;
      };
      viewer = {
        pager = "less -R";
        alternatives = "text/plain,text/html";
      };
      compose = {
        editor = "hx";
        address-book-cmd = "";
      };
      filters = {
        "text/plain" = "colorize";
        "text/html" = "html";
      };
    };

    # Edit like Helix: aerc drops into $EDITOR (hx) for compose, and the
    # default keybindings are already broadly vi-like. A few tweaks to
    # bring it closer to the Helix muscle-memory used everywhere else.
    extraBinds = {
      messages = {
        j = ":next<Enter>";
        k = ":prev<Enter>";
        gg = ":select 0<Enter>";
        G = ":select -1<Enter>";
        "<C-d>" = ":next 50%<Enter>";
        "<C-u>" = ":prev 50%<Enter>";
        space = ":next<Enter>";
      };
    };
  };
}
