# Discord bridge retired. History collection is performed separately and
# only on demand; no Discord appservice is registered with Synapse.
# The existing /var/lib/mautrix-discord data is NOT deleted by NixOS.
{ ... }:
{
  services.mautrix-discord.enable = false;
}
