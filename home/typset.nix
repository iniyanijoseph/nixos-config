{ pkgs, ... }:
let
  # Keep a complete TeX environment available. Theory papers and downloaded
  # LaTeX sources routinely use packages outside scheme-medium; using the full
  # scheme avoids otherwise mysterious "file not found" compile failures.
  tex = pkgs.texlive.combined.scheme-full;

  # A Typst-like frontend for LaTeX:
  #   ltx c FILE.tex             compile once, keep only the PDF
  #   ltx w FILE.tex             recompile when TeX/Bib files change
  #   ltx clean FILE.tex         remove auxiliary files, keep the PDF
  #   ltx distclean FILE.tex     remove auxiliary files and the PDF
  #   ltx typst FILE.tex [OUT]   convert to standalone Typst with Pandoc
  ltx = pkgs.writeShellApplication {
    name = "ltx";
    runtimeInputs = with pkgs; [
      coreutils
      pandoc
      watchexec
    ];
    text = ''
      set -eu

      usage() {
        cat <<'EOF'
Usage:
  ltx c FILE.tex
  ltx w FILE.tex
  ltx clean FILE.tex
  ltx distclean FILE.tex
  ltx typst FILE.tex [OUTPUT.typ]

Commands:
  c, compile       Compile to PDF and remove LaTeX auxiliary files.
  w, watch         Recompile on .tex/.bib/.sty/.cls/.bst changes.
  clean            Remove auxiliary files but keep the PDF.
  distclean        Remove auxiliary files and the generated PDF.
  typst, to-typst  Convert LaTeX to a standalone Typst source with Pandoc.
EOF
      }

      require_source() {
        if [[ "$#" -lt 1 || ! -f "$1" ]]; then
          echo "ltx: expected an existing .tex file" >&2
          exit 2
        fi
        realpath "$1"
      }

      compile_one() {
        local source_file="$1"
        local source_dir source_name

        source_dir="$(dirname "$source_file")"
        source_name="$(basename "$source_file")"

        (
          cd "$source_dir"
          ${tex}/bin/latexmk \
            -pdf \
            -interaction=nonstopmode \
            -halt-on-error \
            -file-line-error \
            "$source_name"

          # latexmk -c removes .aux/.log/.fls/.fdb_latexmk/etc. while keeping
          # the generated PDF.
          ${tex}/bin/latexmk -c "$source_name" >/dev/null
        )

        echo "Wrote: $source_dir/$(basename "$source_name" .tex).pdf"
      }

      clean_one() {
        local source_file="$1"
        local remove_pdf="$2"
        local source_dir source_name

        source_dir="$(dirname "$source_file")"
        source_name="$(basename "$source_file")"

        (
          cd "$source_dir"
          if [[ "$remove_pdf" == "1" ]]; then
            ${tex}/bin/latexmk -C "$source_name"
          else
            ${tex}/bin/latexmk -c "$source_name"
          fi
        )
      }

      if [[ "$#" -lt 1 ]]; then
        usage
        exit 2
      fi

      command="$1"
      shift

      case "$command" in
        c|compile)
          source_file="$(require_source "''${1:-}")"
          compile_one "$source_file"
          ;;

        w|watch)
          source_file="$(require_source "''${1:-}")"
          source_dir="$(dirname "$source_file")"

          echo "Watching $source_dir"
          echo "Main file: $source_file"

          # Only source-like extensions trigger a rebuild, so cleanup and PDF
          # writes do not create a recompilation loop.
          watchexec \
            --watch "$source_dir" \
            --exts tex,bib,sty,cls,bst \
            --restart \
            -- "$0" c "$source_file"
          ;;

        clean)
          source_file="$(require_source "''${1:-}")"
          clean_one "$source_file" 0
          ;;

        distclean)
          source_file="$(require_source "''${1:-}")"
          clean_one "$source_file" 1
          ;;

        typst|to-typst)
          source_file="$(require_source "''${1:-}")"
          source_dir="$(dirname "$source_file")"
          source_name="$(basename "$source_file")"

          if [[ "$#" -ge 2 ]]; then
            output_file="$(realpath -m "$2")"
          else
            output_file="$source_dir/$(basename "$source_name" .tex).typ"
          fi

          # --standalone is important: Pandoc's Typst writer then preserves
          # document metadata and bibliography declarations instead of
          # emitting only a body fragment.
          (
            cd "$source_dir"
            pandoc "$source_name" \
              --from=latex \
              --to=typst \
              --standalone \
              --wrap=none \
              --output="$output_file"
          )

          echo "Wrote: $output_file"
          ;;

        -h|--help|help)
          usage
          ;;

        *)
          echo "ltx: unknown command: $command" >&2
          usage >&2
          exit 2
          ;;
      esac
    '';
  };
in
{
  home.packages = [
    pkgs.typst
    pkgs.tinymist
    pkgs.typstyle
    pkgs.harper
    tex
    ltx
  ];
}
