from agno.team import Team

from Agents.team.office_team import create_office_team
from api.constants import FILE_DOWNLOAD_HINT

office_team = create_office_team(team_id="office_team")

all_teams = [
    office_team,
]

for team in list(all_teams):
    if not isinstance(team, Team):
        all_teams.remove(team)

# ── 为 team 追加文件下载提示 ──
for team in all_teams:
    if hasattr(team, "instructions") and team.instructions:
        team.instructions += FILE_DOWNLOAD_HINT  # ty:ignore[unsupported-operator]
