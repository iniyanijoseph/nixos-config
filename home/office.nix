{pkgs,...}:
{
	home.packages = with pkgs; [ foliate ];
	programs.onlyoffice.enable = true;
}
