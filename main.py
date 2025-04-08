import requests
import re
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("futaba")

# Constants
FUTABA_URL = "https://may.2chan.net/b/futaba.php"

@mcp.tool()
async def get_thread(thread_id: int, filter_top_sod: bool = True) -> str:
    """Get the content of a specific thread from futaba board.
    
    Args:
        thread_id: The ID of the thread to fetch
        filter_top_sod: If True, only returns posts with "そうだね" counts in the top 25% (default: True)
        
    Returns a formatted string with the thread's posts and "そうだね" counts.
    """
    # Get thread HTML data
    thread_url = f"https://may.2chan.net/b/res/{thread_id}.htm"
    response = requests.get(thread_url)
    bs = BeautifulSoup(response.text, "html.parser")
    
    # Find the main thread post
    thread_bs = bs.find("div", class_="thre")
    if not thread_bs:
        return f"Thread {thread_id} not found or could not be parsed."
    
    thread = {"posts": []}
    
    # Parse post function
    def parse_post(post_bs):
        post = {}
        
        def gettext_strip(x):
            return x.get_text(strip=True) if x else ""
        
        post["sod"] = gettext_strip(post_bs.find("a", class_="sod"))
        post["body"] = post_bs.find("blockquote").get_text(separator="<br>", strip=True)
        
        return post
    
    # Parse the main post
    thread["posts"].append(parse_post(thread_bs))
    
    # Parse reply posts
    for i in bs.find_all("table", border=0):
        thread["posts"].append(parse_post(i))
    
    # Convert to DataFrame
    df_thread = pd.DataFrame.from_dict(thread["posts"])
    
    # Parse "そうだね" counts
    def parse_sod(s):
        if s == "+":
            return 0
        elif s.startswith("そうだねx"):
            return int(s.replace("そうだねx", ""))
        return 0  # Default case
    
    # Apply conversion
    df_thread['sod_num'] = df_thread['sod'].apply(parse_sod)
    
    # Filter posts if requested
    if filter_top_sod and len(df_thread) > 1:  # Only filter if there's more than one post
        # Calculate the 75th percentile threshold
        threshold = df_thread['sod_num'].quantile(0.75)
        
        # Create a mask to keep the OP and posts with sod_num above threshold
        mask = (df_thread.index == 0) | (df_thread['sod_num'] >= threshold)
        
        # Apply the filter
        filtered_df = df_thread[mask].copy()
        
        # Add info about filtering
        total_posts = len(df_thread)
        kept_posts = len(filtered_df)
        filter_info = f"Showing {kept_posts} out of {total_posts} posts (OP + top 25% by そうだね count)"
        
        # Use the filtered DataFrame
        df_to_display = filtered_df
    else:
        # Use all posts
        filter_info = "Showing all posts"
        df_to_display = df_thread
    
    # Format results
    lines = []
    
    # Add filter info as the first line
    lines.append(filter_info)
    
    # Add each post
    for i, (idx, row) in enumerate(df_to_display.iterrows()):
        # For the original post (always included)
        if idx == 0:
            post_type = "OP"
        else:
            # For replies, show the actual reply number from the original thread
            post_type = f"返信 #{idx}"
        
        lines.append(
            f"{post_type}:\n"
            f"投稿: {row['body']}\n"
            f"そうだね数: {row['sod_num']}"
        )
    
    # Combine all posts into a single string
    result_text = "\n\n".join(lines)
    
    return result_text

@mcp.tool()
async def get_futaba() -> str:
    """Get a list of threads from futaba board sorted by momentum.
    
    Returns a formatted string with thread IDs, titles, reply counts, and momentum.
    """
    # Get HTML data
    html_response = requests.get(
        f"{FUTABA_URL}?mode=cat", 
        cookies={"cxyl": "100x100x100x1x6"}
    )
    bs = BeautifulSoup(html_response.text, "html.parser")
    
    # Parse HTML data
    threads_html = []
    for td in bs.find("table", id="cattable").find_all("td"):
        id_match = re.match(r"res/(\d+?)\.htm", td.a.get("href"))
        id = id_match.group(1)
        
        if td.a.img:
            imageurl = td.a.img.get("src")
        else:
            imageurl = None
            
        title = td.small.get_text()
        
        # "()" で括られてるので[1:-1]で省く
        count = int(td.find("font", size="2").get_text()[1:-1])
        
        threads_html.append({
            "id": int(id), 
            "image_url": imageurl, 
            "title": title, 
            "count": count
        })
    
    df_threads_html = pd.DataFrame.from_dict(threads_html)
    
    # Get JSON data
    json_response = requests.get(f"{FUTABA_URL}?mode=json").json()
    
    threads_json = []
    for k in json_response["res"].keys():
        date = re.sub(r'\(.*?\)', '', json_response["res"][k]["now"])
        date = re.match(r'^\d{2}/\d{2}/\d{2}\d{2}:\d{2}:\d{2}', date)
        date = datetime.strptime(date.group(), "%y/%m/%d%H:%M:%S")
        
        threads_json.append({
            "id": int(k),
            "date": date,
            "comment": json_response["res"][k]["com"], 
        })
    
    df_threads_json = pd.DataFrame.from_dict(threads_json)
    
    # Merge data and calculate momentum
    df_threads = pd.merge(
        df_threads_html,
        df_threads_json,
        on="id",
        how="inner",
    )
    
    now = datetime.now()
    df_threads['ikioi'] = df_threads['count'] / ((now - df_threads['date']).dt.total_seconds() / 3600)
    
    # Sort by momentum
    df_threads = df_threads.sort_values("ikioi", ascending=False)
    
    # Format results
    lines = []
    for _, row in df_threads.iterrows():
        lines.append(
            f"スレッドID: {row['id']}\n"
            f"スレッドタイトル: {row['title']}\n"
            f"レス数: {row['count']}\n"
            f"スレッド勢い: {row['ikioi']:.2f}\n"
        )
    
    # Combine all thread texts into a single string
    result_text = "\n".join(lines)
    
    return result_text

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')
