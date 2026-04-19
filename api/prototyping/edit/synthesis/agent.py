import json
from openai import OpenAI
from api.prototyping.edit.index.query import query_clips

def run_synthesis_loop(video_filename: str, instructions: str, openai_api_key: str = None) -> list[dict]:
    """
    Runs an LLM agent loop to construct an AMV timeline based on instructions.
    The agent can call `query_clips` to find timestamps and `add_clip` to build the timeline.
    Returns the final list of timeline events.
    """
    client = OpenAI(api_key=openai_api_key)
    
    system_prompt = """
    You are an expert AMV editor. You must construct a video timeline based on the user's instructions.
    You have access to a semantic search tool `query_clips` which lets you find timestamps in the source video matching a text query.
    
    Steps:
    1. Analyze the requested music pacing and structure.
    2. Use `query_clips` multiple times to find suitable shots (e.g. "explosion", "sad face").
    3. Construct the timeline by matching shots to the beat/pacing requirements.
    4. Call `finish_edit` with the final timeline.
    
    Your timeline MUST be continuous without overlapping clips.
    """
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "query_clips",
                "description": "Finds the top K timestamps in the source video that match the semantic description.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Visual description of what to search for (e.g. 'person falling', 'explosion')"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results to return (default 5)"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "finish_edit",
                "description": "Submits the final timeline and ends the synthesis loop.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timeline": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "start_time": {"type": "number", "description": "Start time in seconds"},
                                    "end_time": {"type": "number", "description": "End time in seconds"},
                                    "source_timestamp": {"type": "number", "description": "Timestamp from query_clips"}
                                },
                                "required": ["start_time", "end_time", "source_timestamp"]
                            }
                        }
                    },
                    "required": ["timeline"]
                }
            }
        }
    ]
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": instructions}
    ]
    
    max_loops = 10
    loops = 0
    
    while loops < max_loops:
        print(f"Agent thinking (loop {loops+1})...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        
        msg = response.choices[0].message
        messages.append(msg)
        
        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                print(f"Agent called tool: {name} with args: {args}")
                
                if name == "query_clips":
                    # Call the actual local proxy
                    query_res = query_clips(args["query"], video_filename, args.get("top_k", 5))
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(query_res)
                    })
                elif name == "finish_edit":
                    print("Agent finished editing.")
                    return args["timeline"]
        else:
            # The model didn't call a tool, it just talked.
            # We force it to continue or we can just return what it said if it failed.
            print(f"Agent response: {msg.content}")
            messages.append({"role": "user", "content": "Please output your timeline using the finish_edit tool."})
            
        loops += 1
        
    raise RuntimeError("Synthesis loop exceeded max iterations without calling finish_edit.")
