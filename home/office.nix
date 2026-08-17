{pkgs,...}:
{
	home.packages = with pkgs; [ jabref zotero];
	programs.onlyoffice.enable = true;
}
