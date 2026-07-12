{pkgs,...}:
{
	home.packages = with pkgs; [ jabref ];
	programs.onlyoffice.enable = true;
}
