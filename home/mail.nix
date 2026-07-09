{ pkgs, ... }:

{
  home.packages = with pkgs; [ oama pass ];

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
      general = { unsafe-accounts-conf = true; };
      ui = { sidebar-width = 24; };
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
