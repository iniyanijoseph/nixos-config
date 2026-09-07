{pkgs, ...}:
let
  # The standard medium TeX Live environment covers common LaTeX, math,
  # graphics, fonts, bibliography support, and the LuaTeX/XeTeX engines.
  # Add the usual build and bibliography frontends explicitly.
  tex = pkgs.texliveMedium.withPackages (ps: with ps; [
    latexmk
    biber
  ]);
in {
  home.packages = with pkgs; [
    typst
    tinymist
    typstyle
    harper
    tex
  ];
}
