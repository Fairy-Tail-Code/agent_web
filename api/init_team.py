from agno.team import Team

from Agents.team.office_team import create_office_team

office_team = create_office_team(team_id="office_team")

all_teams = [
    office_team,
]

for team in list(all_teams):
    if not isinstance(team, Team):
        all_teams.remove(team)

# ── 为 team 追加文件下载提示 ──
_file_download_hint = (
    "\n\n【文件交付规范】当你或团队成员使用工具生成了文件（如 .docx/.pdf/.xlsx/.md 等），"
    "在回复的末尾必须包含该文件的下载链接，格式为：\n"
    "[下载 文件名](/backend/files/download/相对路径)\n"
    "其中「相对路径」是文件相对于 /app/user_cache/ 的路径。"
    "例如文件保存在 /app/user_cache/office/output/docx/报告.docx，"
    "则链接为 [下载 报告.docx](/backend/files/download/office/output/docx/报告.docx)。"
    "可以给出多个文件链接。"
)
for team in all_teams:
    if hasattr(team, "instructions") and team.instructions:
        team.instructions += _file_download_hint  # ty:ignore[unsupported-operator]
