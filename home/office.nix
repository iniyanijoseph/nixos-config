{pkgs,...}:
{
	home.packages = with pkgs; [ lorien ];
	programs.onlyoffice.enable = true;
}
