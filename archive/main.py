from graph import agent
from tools import log_conversation

while True:
    query = input("> ")

    if query == "exit":
        break

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": query,
                }
            ]
        }
    )

    response = result["messages"][-1].content
    print(response)
    log_conversation(query, response)
