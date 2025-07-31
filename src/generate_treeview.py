import boto3
from collections import defaultdict
from datetime import timezone
import html

BUCKET_NAME = "knatempstorage"
PREFIX = "fast_historic/nwm/"  # must end with '/' for subfolder
OUTPUT_HTML = "index.html"


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
                    f'<span class="file-date">{date}</span>'
                    f'<a class="file-download" href="{download_link}" target="_blank" title="Download">💾</a>'
                    f"</li>"
                )

            else:
                html_parts.append(
                    f"<li><details open><summary>"
                    f'<span class="tree-line">{html.escape(prefix + branch)}</span>'
                    f'<span class="folder">{html.escape(k)}</span>'
                    f"</summary><ul>"
                )
                html_parts.append(render_node(v, subprefix, last))
                html_parts.append("</ul></details></li>")
        return "\n".join(html_parts)

    return f"<ul class='tree'>{render_node(d)}</ul>"


def list_s3_objects(bucket, prefix):
    s3 = boto3.client("s3", aws_access_key_id="", aws_secret_access_key="")
    paginator = s3.get_paginator("list_objects_v2")
    result = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        result.extend(page.get("Contents", []))
    return result


def generate_html(bucket, prefix, output_html):
    objects = list_s3_objects(bucket, prefix)
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
        cursor: pointer;
        list-style: none;
        outline: none;
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
    {body}
</body>
</html>"""

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html_str)
    print(f"HTML saved to {output_html}")


if __name__ == "__main__":
    # generate the index html
    generate_html(BUCKET_NAME, PREFIX, OUTPUT_HTML)
    # Optional upload to S3
