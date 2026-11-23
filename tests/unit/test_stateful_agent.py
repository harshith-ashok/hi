from hi.agents.term.term import _StatefulAgent


class Inner:
    """Stands in for the real agent: records what it is sent and answers with the messages plus a reply."""

    def __init__(self):
        self.sent = []

    def stream(self, input, *args, **kwargs):
        self.sent.append([m["content"] for m in input["messages"]])
        yield ((), "values", {"messages": [*input["messages"], {"role": "assistant", "content": f"reply {len(self.sent)}"}]})

    def invoke(self, input, *args, **kwargs):
        self.sent.append([m["content"] for m in input["messages"]])
        return {"messages": [*input["messages"], {"role": "assistant", "content": f"reply {len(self.sent)}"}]}


def user(text):
    return {"role": "user", "content": text}


def history(*pairs):
    return [m for ask, answer in pairs for m in (user(ask), {"role": "assistant", "content": answer})]


def test_a_follow_up_adds_only_the_new_message_to_what_the_agent_remembers():
    inner = Inner()
    agent = _StatefulAgent(inner)
    list(agent.stream({"messages": [user("q1")]}))
    # the server now sends the saved history (q1 and its reply) and the new question
    list(agent.stream({"messages": [*history(("q1", "reply 1")), user("q2")]}))
    assert inner.sent[1] == ["q1", "reply 1", "q2"]  # not q1, reply 1, q1, reply 1, q2


def test_the_memory_does_not_grow_by_the_history_each_turn():
    inner = Inner()
    agent = _StatefulAgent(inner, max_history=1000)
    saved = []
    for n in range(1, 6):
        list(agent.stream({"messages": [*saved, user(f"q{n}")]}))
        saved += history((f"q{n}", f"reply {n}"))
    assert len(inner.sent[-1]) == 2 * 4 + 1  # four earlier exchanges and the new question: no repeats
    assert inner.sent[-1] == [x for n in range(1, 5) for x in (f"q{n}", f"reply {n}")] + ["q5"]


def test_after_a_reset_or_a_restart_the_saved_history_is_used():
    inner = Inner()
    agent = _StatefulAgent(inner)
    list(agent.stream({"messages": [*history(("q1", "a1")), user("q2")]}))  # a new process: memory empty
    assert inner.sent[0] == ["q1", "a1", "q2"]
    agent.reset()
    list(agent.stream({"messages": [*history(("q1", "a1")), user("q3")]}))
    assert inner.sent[1] == ["q1", "a1", "q3"]


def test_invoke_behaves_the_same_and_a_single_message_is_taken_whole():
    inner = Inner()
    agent = _StatefulAgent(inner)
    agent.invoke({"messages": [user("q1")]})
    agent.invoke({"messages": [*history(("q1", "reply 1")), user("q2")]})
    assert inner.sent[1] == ["q1", "reply 1", "q2"]
    agent.invoke({"messages": [user("q3")]})
    assert inner.sent[2][-1] == "q3" and inner.sent[2].count("q3") == 1
