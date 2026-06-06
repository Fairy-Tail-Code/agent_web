from agno.agent import Agent

from Agents.agent.data_agent import create_data_agent
from api import utils

data_agent = create_data_agent(agent_id="data_agent")

all_agents = [
    data_agent,
]

for agent in list(all_agents):
    if not isinstance(agent, Agent):
        all_agents.remove(agent)

if all_agents:
    for agent in all_agents:
        utils.set_default_config_to_agent(agent)
