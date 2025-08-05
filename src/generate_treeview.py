import asyncio
import tempfile
from collections import defaultdict
from datetime import timezone
from aiobotocore.session import get_session
import html
from utils import S3APISettings


# Replace with your desired S3 URL format (e.g., if public or presigned)
def generate_download_link(bucket, key):
    return f"https://{bucket}.s3.amazonaws.com/{key}"


def build_tree_structure(objects):
    tree = lambda: defaultdict(tree)
    root = tree()

    for obj in objects:
        # Strip slashes and split key
        parts = [p for p in obj["Key"].strip("/").split("/") if p]
        current = root
        for part in parts[:-1]:
            current = current[part]
        current[parts[-1]] = {
            "size": obj["Size"],
            "last_modified": obj["LastModified"],
            "key": obj["Key"],
        }

    return root


def render_tree_html(d, bucket):
    def render_node(node, prefix="", is_last=True):
        html_parts = []
        items = sorted(node.items())
        for i, (k, v) in enumerate(items):
            is_leaf = isinstance(v, dict) and "key" in v
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            subprefix = prefix + ("    " if last else "│   ")

            if is_leaf:
                size_kb = v["size"] / 1024
                date = (
                    v["last_modified"]
                    .astimezone(timezone.utc)
                    .strftime("%Y-%m-%d %H:%M:%S UTC")
                )
                download_link = generate_download_link(bucket, v["key"])
                html_parts.append(
                    f'<li class="file-row">'
                    f'<span class="tree-line">{html.escape(prefix + branch)}</span>'
                    f'<span class="file-name">{html.escape(k)}</span>'
                    f'<span class="file-size">{size_kb:.1f} KB</span>'
                    f'<span class="file-date" data-timestamp="{v["last_modified"].isoformat()}">{date}</span>'
                    f'<a class="file-download" href="{download_link}" target="_blank" title="Download">💾</a>'
                    f"</li>"
                )

            else:
                html_parts.append(
                    f"<li><details open><summary>"
                    f'<div style="display: flex; align-items: center;">'
                    f'<span class="tree-line">{html.escape(prefix + branch)}</span>'
                    f'<span class="folder">{html.escape(k)}</span>'
                    f"</div></summary><ul>"
                )
                html_parts.append(render_node(v, subprefix, last))
                html_parts.append("</ul></details></li>")
        return "\n".join(html_parts)

    return f"<ul class='tree'>{render_node(d)}</ul>"


async def list_s3_objects(bucket: str, prefix: str):
    s3settings = S3APISettings()
    session = get_session()

    async with session.create_client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id=s3settings.access_key_id,
        aws_secret_access_key=s3settings.secret_access_key,
    ) as s3:
        paginator = s3.get_paginator("list_objects_v2")
        result = []
        async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            result.extend(page.get("Contents", []))
        return result


async def generate_html(
    bucket: str, prefix: str, output_html: str = None, s3_upload: bool = True
):
    s3settings = S3APISettings()
    session = get_session()

    objects = await list_s3_objects(bucket, prefix)
    tree = build_tree_structure(objects)
    subtree = tree
    for part in prefix.strip("/").split("/"):
        subtree = subtree.get(part, {})
    body = render_tree_html(subtree, bucket)

    html_str = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>S3 Tree View</title>
    <style>
    body {{
        font-family: monospace;
        background-color: #f9f9f9;
        padding: 1em 2em;
    }}
    ul.tree, ul.tree ul {{
        list-style: none;
        margin: 0;
        padding-left: 1em;
    }}
    ul.tree li::marker {{
        content: '';
    }}
    details summary {{
        display: flex;
        align-items: center;
        cursor: pointer;
        list-style: none;
        outline: none;
        padding-left: 0;
    }}

    details > ul {{
        padding-left: 1.8em;
    }}
    .folder {{
        font-weight: bold;
        color: #2a52be;
    }}  
    .file-row {{
        display: grid;
        grid-template-columns: 2em 440px 100px 220px 2em;
        gap: 0.5em;
        align-items: center;
        margin: 2px 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .tree-line {{
        color: #888;
    }}
    .file-name {{
        color: #333;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        display: inline-block;
    }}
    .file-size {{
        text-align: right;
        color: #555;
    }}
    .file-date {{
        color: #777;
        font-size: 0.9em;
    }}
    .file-row {{
        display: grid;
        grid-template-columns: 2em 440px 100px 220px 140px 2em;
        gap: 0.5em;
        align-items: center;
        margin: 2px 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}

    .file-age {{
        color: #999;
        text-align: right;
        font-size: 0.9em;
    }}
    .file-download {{
        text-align: center;
        text-decoration: none;
        font-size: 1.1em;
    }}
    .file-download:hover {{
        text-decoration: underline;
    }}
</style>
</head>
<body>
    <h2>Files in s3://{bucket}/{prefix}</h2>
    <div class="file-header">
        <span></span>
        <span>File</span>
        <span style="text-align: right;">Size</span>
        <span style="text-align: left;">Date</span>
        <span style="text-align: right;">Age</span>
        <span style="text-align: center;">Download</span>
    </div>
    {body}
    <script>
    function formatAge(timestamp) {{
        const now = new Date();
        const fileDate = new Date(timestamp);
        const diffMs = now - fileDate;

        const minutes = Math.floor(diffMs / 60000);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (days > 0) return `${{days}}d ${{hours % 24}}h`;
        if (hours > 0) return `${{hours}}h ${{minutes % 60}}m`;
        return `${{minutes}}m`;
    }}

    document.querySelectorAll(".file-date").forEach(el => {{
        const ts = el.dataset.timestamp;
        const ageSpan = document.createElement("span");
        ageSpan.className = "file-age";
        ageSpan.textContent = formatAge(ts);
        el.parentElement.insertBefore(ageSpan, el.nextSibling);
    }});
    </script>
</body>
</html>"""

    if output_html is None:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".html", mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write(html_str)
            output_html = tmp.name
    else:
        with open(output_html, "w", encoding="utf-8") as f:
            f.write(html_str)

    if s3_upload:
        async with session.create_client(
            "s3",
            region_name="us-west-1",
            aws_access_key_id=s3settings.access_key_id,
            aws_secret_access_key=s3settings.secret_access_key,
        ) as s3:
            await s3.put_object(
                Bucket=bucket,
                Key=f"{prefix.rstrip('/')}/{output_html}",
                Body=html_str.encode("utf-8"),
                ContentType="text/html",
                CacheControl="max-age=300"
            )

    return output_html


# async def upload_html_to_s3(file_bytes: bytes, bucket: str, key: str):
#     s3settings = S3APISettings()
#     session = get_session()
#     async with session.create_client(
#         "s3",
#         region_name="us-west-1",
#         aws_access_key_id=s3settings.access_key_id,
#         aws_secret_access_key=s3settings.secret_access_key,
#     ) as s3:
#         await s3.put_object(
#             Bucket=bucket,
#             Key=key,
#             Body=file_bytes,
#             ContentType="text/html",
#             CacheControl="max-age=3600",
#             ACL="public-read"
#         )


BUCKET_NAME = "knatempstorage"
PREFIX = "fast_historic/da/"  # must end with '/' for subfolder
OUTPUT_HTML = "index.html"

if __name__ == "__main__":
    # generate the index html
    asyncio.run(
        generate_html(
            bucket=BUCKET_NAME, prefix=PREFIX, output_html=OUTPUT_HTML, s3_upload=True
        )
    )
    # Optional upload to S3
