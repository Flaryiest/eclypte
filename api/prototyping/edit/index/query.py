import modal

def query_clips(query: str, video_filename: str, top_k: int = 5) -> list[dict]:
    """
    Locally callable function that proxies to the Modal query endpoint.
    Retrieves the top K matching timestamps for the text query from the video's CLIP index.
    """
    try:
        query_func = modal.Function.from_name("eclypte-query", "query_index")
    except modal.exception.NotFoundError:
        raise RuntimeError("Could not find Modal function eclypte-query::query_index. Have you deployed it?")
        
    return query_func.remote(query, video_filename, top_k)
