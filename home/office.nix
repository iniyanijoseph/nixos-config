{pkgs,...}:
{
	home.packages = with pkgs; [etherpad-lite];
	programs.onlyoffice.enable = true;
	# programs.onlyoffice.settings = {
	# 	UITheme="theme-dark";
	# };
}
