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
          header_file="$cache_dir/math-preview-header.html"

          cat > "$header_file" <<'EOF'
<style>
  :root {
    color-scheme: dark;
  }
  html {
    background: #1d2021;
  }
  body {
    box-sizing: border-box;
    max-width: 960px;
    margin: 0 auto;
    padding: 3rem 4rem 6rem;
    background: #1d2021;
    color: #ebdbb2;
    font-family: ui-serif, "Libertinus Serif", "STIX Two Text", serif;
    font-size: 18px;
    line-height: 1.65;
  }
  h1, h2, h3, h4, h5, h6 {
    color: #fabd2f;
    line-height: 1.25;
    margin-top: 1.7em;
  }
  h1 {
    border-bottom: 1px solid #504945;
    padding-bottom: 0.25em;
  }
  a {
    color: #83a598;
  }
  strong {
    color: #fbf1c7;
  }
  blockquote {
    margin-left: 0;
    padding-left: 1rem;
    border-left: 3px solid #689d6a;
    color: #d5c4a1;
  }
  code, pre {
    font-family: "Maple Mono", "JetBrainsMono Nerd Font", monospace;
  }
  code {
    background: #282828;
    padding: 0.12em 0.3em;
    border-radius: 4px;
  }
  pre {
    overflow-x: auto;
    padding: 1rem;
    background: #282828;
    border: 1px solid #3c3836;
    border-radius: 6px;
  }
  pre code {
    padding: 0;
  }
  table {
    border-collapse: collapse;
    width: 100%;
    margin: 1.5rem 0;
  }
  th, td {
    border: 1px solid #504945;
    padding: 0.45rem 0.65rem;
    text-align: left;
  }
  th {
    background: #282828;
  }
  img, svg {
    max-width: 100%;
  }
  mjx-container[display="true"] {
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0.7rem 0;
  }
  .math.display {
    overflow-x: auto;
  }
  @media (max-width: 760px) {
    body {
      padding: 1.5rem 1.2rem 4rem;
      font-size: 16px;
    }
  }
</style>
<script>
  window.MathJax = {
    tex: {
      tags: "ams",
      processEscapes: true
    },
    chtml: {
      scale: 1.05
    }
  };
</script>
EOF

          pandoc \
            --standalone \
            --from=markdown+tex_math_dollars+tex_math_single_backslash+raw_tex \
            --mathjax \
            --section-divs \
            --include-in-header="$header_file" \
            --metadata title="$(basename "$source_file")" \
            "$source_file" \
            --output "$output_file"
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
        # Keep Helix's system-clipboard paste bindings; Space+m previews docs.
        space.p = "paste_clipboard_after";
        space.P = "paste_clipboard_before";
        space.m = [ ":w" ":sh doc-preview \"%{buffer_name}\"" ];
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
        # Keep Helix's system-clipboard paste bindings; Space+m previews docs.
        space.p = "paste_clipboard_after";
        space.P = "paste_clipboard_before";
        space.m = [ ":w" ":sh doc-preview \"%{buffer_name}\"" ];
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
