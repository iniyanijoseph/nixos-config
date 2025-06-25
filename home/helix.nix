{pkgs, ...}:
{
  home.packages = with pkgs; [ pragtical micro];
  programs.helix = {
    enable = true;
    defaultEditor = true;
    settings = {
      theme = "gruvbox_dark_hard";
      editor.cursor-shape = {
        normal = "block";
        insert = "bar";
        select = "underline";
      };

      editor.file-picker.hidden = false;
      keys.normal = {
        space.w = ":w";
        space.x = ":x";
        pageup = "no_op";
        home = "no_op";
        end = "no_op";
        A-space = "normal_mode";
        A-w = "vsplit";
        A-n = "rotate_view";
        A-q = "wclose";
        "#" = "toggle_comments";
        "ret" = ["open_below" "normal_mode"];
        h = "move_char_right";
        l = "move_char_left";
        g.h = "goto_line_end";
        g.l = "goto_line_start";
      };

      editor.soft-wrap.enable = true;
  
      keys.select= {
        space.w = ":w";
        space.x = ":x";
        pageup = "no_op";
        home = "no_op";
        end = "no_op";
        A-space = "normal_mode";
        A-w = "vsplit";
        A-n = "rotate_view";
        A-q = "wclose";
        "#" = "toggle_comments";
        "ret" = ["open_below" "normal_mode"];
        h = "move_char_right";
        l = "move_char_left";
        g.h = "goto_line_end";
        g.l = "goto_line_start";
      };
      keys.insert = {
        pageup = "no_op";
        home = "no_op";
        end = "no_op";
        A-space = "normal_mode";
        A-w = "vsplit";
        A-n = "rotate_view";
        A-q = "wclose";
      };
    };

    languages = {
      language = [
      {
        name = "typst";
        language-servers = ["tinymist"];
      }

      ];
 
      language-server.tinymist = {
        command = "tinymist";
        config = {
          preview = {
            background = {
              enabled = true;
              args = ["--data-plane-host=127.0.0.1:23635" "--invert-colors=never" "--open"];
            };
            cursorIndicator = true;
            scrollSync = true;
          };
          exportPdf = "onType";
          formatterMode = "typstfmt";
        };
      };
    };

  };
}
