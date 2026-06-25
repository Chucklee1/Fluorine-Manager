# Support package for the OpenMW (Morrowind) game plugin.
#
# This is a plain subpackage, not an auto-discovered game module: basic_games'
# createPlugins() only imports top-level games/*.py files and games/**/plugins/
# __init__.py entry points, so the helpers here are loaded only when
# game_openmw.py imports them.
