"""Build a private C3 drill in an owned retail episode, preserving the map and stock doors."""
import argparse
import json
from pathlib import Path

from . import controlled_opening
from .analysis.c3_door_stalls import EPISODE_SHA, MAP_SHA


COG = "cog/ctf_respawn.cog"
# Stock C3's ghost is template zero, which JK rejects in GetTemplateByIndex.
# Its noncolliding, model-free _ghoststructure is a usable temporary marker.
SYMBOLS = """template c3AnchorTemplate=_ghoststructure local
thing c3Anchor=-1 local
thing c3Player=-1 local
int c3Team=-1 local
int c3Placed=0 local
int c3Sector=-1 local
int c3LastSector=-1 local
int c3LastFlag=-1 local
int c3LastKeys=-1 local
int c3LastAlive=-1 local
int c3Flag=0 local
int c3Keys=0 local
int c3Alive=0 local
flex c3Ready=-1.0 local
flex c3Next=0.0 local
vector c3Position local
message pulse
message newplayer
"""
LOG = """   PrintInt(GetPlayerNum(c3Player));
   PrintInt(GetPlayerTeam(c3Player));
   PrintFlex(GetLevelTime());
   PrintInt(GetThingSector(c3Player));
   PrintVector(GetThingPos(c3Player));
   PrintVector(GetThingLVec(c3Player));
   PrintFlex(GetThingHealth(c3Player));
   PrintInt(GetInv(c3Player,83));
   PrintInt(GetInv(c3Player,84));
   PrintInt(GetInv(c3Player,81));
   PrintInt(GetInv(c3Player,82));
"""
HANDLERS = """
newplayer:
   if (!c3Placed || GetSenderRef() != c3Player) return;
   Print("C3_MATCH_NEWLIFE_V1");
   call c3Log;
   return;

pulse:
   c3Player = GetLocalPlayerThing();
   if (c3Player < 0) return;
   c3Team = GetPlayerTeam(c3Player);
   if (!c3Placed)
   {
      if (GetThingHealth(c3Player) <= 0 || GetNumPlayersInTeam(1) < 1 || GetNumPlayersInTeam(2) < 1) return;
      if (c3Team == 1 && GetInv(c3Player,83) == 1 && GetInv(c3Player,84) == 0)
      {
         c3Sector = 505;
         c3Position = '-5.612 -0.563 2.370';
      }
      else if (c3Team == 2 && GetInv(c3Player,83) == 0 && GetInv(c3Player,84) == 1)
      {
         c3Sector = 393;
         c3Position = '-2.046 -1.758 2.620';
      }
      else return;
      if (c3Ready < 0) c3Ready = GetLevelTime();
      if (GetLevelTime() - c3Ready < 0.6) return;
      c3Anchor = CreateThingAtPos(c3AnchorTemplate,c3Sector,c3Position,'0 0 0');
      if (c3Anchor < 0) return;
      c3Placed = 1;
      Print("C3_MATCH_TEAMS_V1");
      PrintInt(GetNumPlayersInTeam(1));
      PrintInt(GetNumPlayersInTeam(2));
      StopThing(c3Player);
      TeleportThing(c3Player,c3Anchor);
      SyncThingPos(c3Player);
      DestroyThing(c3Anchor);
      Print("C3_MATCH_START_V1");
      call c3Log;
   }
   c3Sector = GetThingSector(c3Player);
   c3Flag = GetInv(c3Player,81) + 2*GetInv(c3Player,82);
   c3Keys = GetInv(c3Player,83) + 2*GetInv(c3Player,84);
   c3Alive = (GetThingHealth(c3Player) > 0);
   if (c3Sector != c3LastSector || c3Flag != c3LastFlag || c3Keys != c3LastKeys ||
       c3Alive != c3LastAlive || GetLevelTime() >= c3Next)
   {
      Print("C3_MATCH_OBS_V1");
      call c3Log;
      c3LastSector = c3Sector;
      c3LastFlag = c3Flag;
      c3LastKeys = c3Keys;
      c3LastAlive = c3Alive;
      c3Next = GetLevelTime() + 1.0;
   }
   return;

c3Log:
""" + LOG + "   return;\n"


def build(source, output):
    """Write the private drill to a new GOB and return its reproducibility receipt."""
    if controlled_opening.digest(source.read_bytes()) != EPISODE_SHA:
        raise ValueError("The C3 drill requires the stock JK1CTF episode")
    entries = controlled_opening.read_entries(source)
    if controlled_opening.digest(entries["jkl/c3.jkl"]) != MAP_SHA:
        raise ValueError("The C3 map must match the door controller")
    original = entries[COG]
    text = original.decode("ascii").replace("\r\n", "\n")
    text = controlled_opening.replace_once(text, "message     startup", SYMBOLS + "\nmessage     startup")
    text = controlled_opening.replace_once(text, "SetRespawnMask(player, 0x0000FFFF);", """SetRespawnMask(player, 0x0000FFFF);
   Print("C3_FIXTURE_LOADED_V1");
   SetPulse(0.1);""")
    head, separator, tail = text.rpartition("\nend")
    if not head or tail.strip():
        raise ValueError("Unexpected end of the retail COG")
    entries[COG] = (head + HANDLERS + separator + tail).replace("\n", "\r\n").encode("ascii")
    with output.open("xb") as stream:
        stream.write(controlled_opening.encode_entries(entries))
    if controlled_opening.read_entries(output) != entries:
        raise ValueError("Private episode readback differs")
    return dict(episode_sha256=controlled_opening.digest(output.read_bytes()), map_sha256=MAP_SHA,
                stock_episode_sha256=EPISODE_SHA, changed_entry=COG,
                original_cog_sha256=controlled_opening.digest(original),
                fixture_cog_sha256=controlled_opening.digest(entries[COG]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.stock, args.output), indent=2))
