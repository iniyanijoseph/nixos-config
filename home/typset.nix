{pkgs, ...}:
let
  tex = (pkgs.texlive.combine {
    inherit (pkgs.texlive) scheme-medium
      wrapfig amsmath ulem hyperref capt-of
      luatex;
  });
in {
  home.packages = with pkgs; [
    typst
    tinymist
    typstyle
    harper
    tex
  ];
}
