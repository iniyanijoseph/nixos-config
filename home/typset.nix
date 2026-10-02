{pkgs, ...}:
let
  # Keep a complete TeX environment available. Theory papers and downloaded
  # LaTeX sources routinely use packages outside scheme-medium; using the full
  # scheme avoids otherwise mysterious "file not found" compile failures.
  tex = pkgs.texlive.combined.scheme-full;
in {
  home.packages = with pkgs; [
    typst
    tinymist
    typstyle
    harper
    tex
  ];
}
