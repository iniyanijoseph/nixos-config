{pkgs, ...}:
let
  doc-preview = pkgs.writeShellApplication {
    name = "doc-preview";
    runtimeInputs = with pkgs; [
      coreutils
      pandoc
      xdg-utils
      zathura
    ];
    text = ''
      if [ "$#" -ne 1 ] || [ -z "$1" ]; then
        echo "usage: doc-preview FILE" >&2
        exit 2
      fi

      source_file="$1"
      case "$source_file" in
        *.md|*.markdown)
          cache_dir="''${XDG_CACHE_HOME:-$HOME/.cache}/helix-preview"
          mkdir -p "$cache_dir"
          digest="$(printf '%s' "$source_file" | sha256sum | cut -d' ' -f1)"
          output_file="$cache_dir/$digest.html"
          pandoc --standalone --mathjax --metadata title="$(basename "$source_file")" \
            "$source_file" --output "$output_file"
          xdg-open "$output_file" >/dev/null 2>&1 &
          ;;
        *.tex)
          source_dir="$(dirname "$source_file")"
          source_name="$(basename "$source_file")"
          pdf_file="$source_dir/''${source_name%.tex}.pdf"
          (cd "$source_dir" && latexmk -pdf -interaction=nonstopmode -synctex=1 "$source_name")
          zathura "$pdf_file" >/dev/null 2>&1 &
          ;;
        *)
          echo "doc-preview supports Markdown and LaTeX files" >&2
          exit 2
          ;;
      esac
    '';
  };
in
{
  home.packages = with pkgs; [
    micro
    vscodium
    marksman
    markdown-oxide
    texlab
    zathura
    glow
    pandoc
    doc-preview
  ];
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
        space.r = ":reload-all";
        space.p = [ ":w" ":sh doc-preview \"%{buffer_name}\"" ];
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
        space.p = [ ":w" ":sh doc-preview \"%{buffer_name}\"" ];
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
          language-servers = [ "tinymist" "harper-ls" ];
        }
        {
          name = "markdown";
          language-servers = [ "markdown-oxide" "harper-ls" ];
          text-width = 88;
          soft-wrap = {
            enable = true;
            wrap-at-text-width = true;
          };
        }
        {
          name = "latex";
          language-servers = [ "texlab" "harper-ls" ];
        }
        {
          name = "bibtex";
          language-servers = [ "texlab" ];
        }
      ];

      language-server.harper-ls = {
        command = "harper-ls";
        args = ["--stdio"];
      };

      language-server.markdown-oxide = {
        command = "markdown-oxide";
      };

      language-server.texlab = {
        command = "texlab";
        config.texlab = {
          build = {
            executable = "latexmk";
            args = [
              "-pdf"
              "-interaction=nonstopmode"
              "-synctex=1"
              "%f"
            ];
            onSave = true;
            forwardSearchAfter = true;
          };
          forwardSearch = {
            executable = "zathura";
            args = [ "--synctex-forward" "%l:1:%f" "%p" ];
          };
          chktex = {
            onOpenAndSave = true;
            onEdit = true;
          };
        };
      };

      # language-server.llm-lsp = {
      #   command = "llm-lsp"
      #   orgs = ["server", "-p", "codeium"]
      # }
 
      language-server.tinymist = {
        command = "tinymist";
        config = {
          preview = {
            background = {
              enabled = true;
              args = ["--data-plane-host=127.0.0.1:3635" "--invert-colors=never" "--open"];
            };
            cursorIndicator = true;
            scrollSync = true;
          };
          exportPdf = "onType";
          formatterMode = "typstyle";
        };
      };
    };

  };
}
