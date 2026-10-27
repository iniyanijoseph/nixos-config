{ config, lib, ... }:
{
  options.contabo.integrations.enable = lib.mkEnableOption "provisioned messaging integrations";
  config = lib.mkIf config.contabo.integrations.enable {
    contabo.messagingBridges.sms.enable = lib.mkForce true;
    contabo.messagingBridges.slack.enable = lib.mkForce true;
    contabo.emailBridge.enable = lib.mkForce true;
  };
}
