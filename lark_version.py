import json
import logging

logging.basicConfig(level=logging.INFO)

import argparse
import datetime
import json
import logging
import os
import re
import uuid

import arxiv
import lark_oapi as lark
import requests
import yaml
from langchain_openai import ChatOpenAI
from lark_oapi.api.im.v1 import *

logging.basicConfig(
    format="[%(asctime)s %(levelname)s] %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
)

base_url = "https://arxiv.paperswithcode.com/api/v0/papers/"
github_url = "https://api.github.com/search/repositories"
arxiv_url = "http://arxiv.org/"

model_name = os.environ.get("LLM_MODEL_NAME")
api_key = os.environ.get("OPENAI_API_KEY")
api_base = os.environ.get("OPENAI_API_BASE")
app_key = os.environ.get("APP_KEY")
app_secret = os.environ.get("APP_SECRET")
open_id = os.environ.get("OPEN_ID")


def load_config(config_file: str) -> dict:
    """
    config_file: input config file path
    return: a dict of configuration
    """

    # make filters pretty
    def pretty_filters(**config) -> dict:
        keywords = dict()
        EXCAPE = '"'
        QUOTA = ""  # NO-USE
        OR = "OR"  # TODO

        def parse_filters(filters: list):
            ret = ""
            for idx in range(0, len(filters)):
                filter = filters[idx]
                if len(filter.split()) > 1:
                    ret += EXCAPE + filter + EXCAPE
                else:
                    ret += QUOTA + filter + QUOTA
                if idx != len(filters) - 1:
                    ret += OR
            return ret

        for k, v in config["keywords"].items():
            keywords[k] = parse_filters(v["filters"])
        return keywords

    with open(config_file, "r") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
        config["kv"] = pretty_filters(**config)
        logging.info(f"config = {config}")
    return config


def get_authors(authors, first_author=False):
    output = str()
    if first_author == False:
        output = ", ".join(str(author) for author in authors)
    else:
        output = authors[0]
    return output


def sort_papers(papers):
    output = dict()
    keys = list(papers.keys())
    keys.sort(reverse=True)
    for key in keys:
        output[key] = papers[key]
    return output


def get_code_link(qword: str) -> str:
    """
    This short function was auto-generated by ChatGPT.
    I only renamed some params and added some comments.
    @param qword: query string, eg. arxiv ids and paper titles
    @return paper_code in github: string, if not found, return None
    """
    # query = f"arxiv:{arxiv_id}"
    query = f"{qword}"
    params = {"q": query, "sort": "stars", "order": "desc"}
    r = requests.get(github_url, params=params)
    results = r.json()
    code_link = None
    if results["total_count"] > 0:
        code_link = results["items"][0]["html_url"]
    return code_link


prompt_formate = """
## context
{context}
## task
请你将上述论文摘要翻译为中文，不要输出其他任何无关内容，注意输出的内容中不能包含"|"字符
"""


def llm_generate_summary(prompt):

    msg = prompt_formate.format(context=prompt)

    model = ChatOpenAI(
        model_name=model_name,
        temperature=0.1,
        openai_api_key=api_key,
        openai_api_base=api_base,
    )

    try:
        response = model.invoke(msg)
        rsp = response.content
    except Exception as e:
        logging.error(str(e))
        rsp = prompt

    return rsp


def get_daily_papers(topic, query="agent", max_results=2):
    """
    @param topic: str
    @param query: str
    @return paper_with_code: dict
    """
    # output
    content = dict()
    content_to_web = dict()
    print("-----------------")
    print(f"query is {query}")
    print("-----------------")
    search_engine = arxiv.Search(
        query=query, max_results=max_results, sort_by=arxiv.SortCriterion.SubmittedDate
    )

    for result in search_engine.results():

        paper_id = result.get_short_id()
        paper_title = result.title
        paper_url = result.entry_id
        code_url = base_url + paper_id  # TODO

        paper_abstract = result.summary.replace("\n", " ")
        paper_abstract = llm_generate_summary(paper_abstract)
        paper_abstract = paper_abstract.replace("|", ",")
        paper_abstract = paper_abstract.replace("\n", " ")

        paper_authors = get_authors(result.authors)
        paper_first_author = get_authors(result.authors, first_author=True)
        primary_category = result.primary_category
        publish_time = result.published.date()
        update_time = result.updated.date()
        comments = result.comment

        logging.info(
            f"Time = {update_time} title = {paper_title} author = {paper_first_author}"
        )

        # eg: 2108.09112v1 -> 2108.09112
        ver_pos = paper_id.find("v")
        if ver_pos == -1:
            paper_key = paper_id
        else:
            paper_key = paper_id[0:ver_pos]
        paper_url = arxiv_url + "abs/" + paper_key

        try:
            # source code link
            r = requests.get(code_url).json()
            repo_url = None
            if "official" in r and r["official"]:
                repo_url = r["official"]["url"]

            if repo_url is not None:
                content[paper_key] = (
                    "|**{}**|**{}**|{} et.al.|[{}]({})|**[link]({})**|**{}**|\n".format(
                        update_time,
                        paper_title,
                        paper_first_author,
                        paper_key,
                        paper_url,
                        repo_url,
                        paper_abstract,
                    )
                )
                content_to_web[paper_key] = (
                    "- {}, **{}**, {} et.al., Paper: [{}]({}), Code: **[{}]({})**".format(
                        update_time,
                        paper_title,
                        paper_first_author,
                        paper_url,
                        paper_url,
                        repo_url,
                        repo_url,
                    )
                )

            else:
                content[paper_key] = (
                    "|**{}**|**{}**|{} et.al.|[{}]({})|null|{}|\n".format(
                        update_time,
                        paper_title,
                        paper_first_author,
                        paper_key,
                        paper_url,
                        paper_abstract,
                    )
                )
                content_to_web[paper_key] = (
                    "- {}, **{}**, {} et.al., Paper: [{}]({}),{}".format(
                        update_time,
                        paper_title,
                        paper_first_author,
                        paper_url,
                        paper_url,
                        paper_abstract,
                    )
                )

            # TODO: select useful comments
            comments = None
            if comments != None:
                content_to_web[paper_key] += f", {comments}\n"
            else:
                content_to_web[paper_key] += f"\n"

        except Exception as e:
            logging.error(f"exception: {e} with id: {paper_key}")

    data = {topic: content}
    data_web = {topic: content_to_web}
    return data, data_web


def update_paper_links(filename):
    """
    weekly update paper links in json file
    """

    def parse_arxiv_string(s):
        parts = s.split("|")
        date = parts[1].strip()
        title = parts[2].strip()
        authors = parts[3].strip()
        arxiv_id = parts[4].strip()
        code = parts[5].strip()
        paper_abstract = parts[6].strip()
        arxiv_id = re.sub(r"v\d+", "", arxiv_id)
        return date, title, authors, arxiv_id, code, paper_abstract

    os.makedirs(os.path.dirname(filename), exist_ok=True)

    if not os.path.exists(filename) or os.path.getsize(filename) == 0:
        with open(filename, "w") as f:
            pass

    with open(filename, "r") as f:
        content = f.read()
        if not content:
            m = {}
        else:
            m = json.loads(content)

        json_data = m.copy()

        for keywords, v in json_data.items():
            logging.info(f"keywords = {keywords}")
            for paper_id, contents in v.items():
                contents = str(contents)

                (
                    update_time,
                    paper_title,
                    paper_first_author,
                    paper_url,
                    code_url,
                    paper_abstract,
                ) = parse_arxiv_string(contents)

                contents = "|{}|{}|{}|{}|{}|{}|\n".format(
                    update_time,
                    paper_title,
                    paper_first_author,
                    paper_url,
                    code_url,
                    paper_abstract,
                )
                json_data[keywords][paper_id] = str(contents)
                logging.info(
                    f"paper_id = {paper_id}, contents = {contents} ,paper_abstract = {paper_abstract}"
                )

                valid_link = False if "|null|" in contents else True
                if valid_link:
                    continue
                try:
                    code_url = base_url + paper_id  # TODO
                    r = requests.get(code_url).json()
                    repo_url = None
                    if "official" in r and r["official"]:
                        repo_url = r["official"]["url"]
                        if repo_url is not None:
                            new_cont = contents.replace(
                                "|null|", f"|**[link]({repo_url})**|"
                            )
                            logging.info(f"ID = {paper_id}, contents = {new_cont}")
                            json_data[keywords][paper_id] = str(new_cont)

                except Exception as e:
                    logging.error(f"exception: {e} with id: {paper_id}")
        # dump to json file
        print(json_data)
        with open(filename, "w") as f:
            json.dump(json_data, f)


def demo(**config):
    # TODO: use config
    data_collector = []
    data_collector_web = []

    keywords = config["kv"]
    max_results = config["max_results"]
    publish_lark = config["publish_lark"]

    b_update = config["update_paper_links"]
    logging.info(f"Update Paper Link = {b_update}")
    if config["update_paper_links"] == False:
        logging.info(f"GET daily papers begin")
        for topic, keyword in keywords.items():
            print(keyword)
            print("=========================")
            logging.info(f"Keyword: {topic}")
            data, data_web = get_daily_papers(
                topic, query=keyword, max_results=max_results
            )
            data_collector.append(data)
            data_collector_web.append(data_web)
            print("\n")
        logging.info(f"GET daily papers end")

    if publish_lark:

        raw_text = ""
        for raw_content in data_collector_web:
            topic = list(raw_content.keys())[0]
            content = list(raw_content.values())[0]
            raw_text += f"topic: {topic} \n\n"
            raw_text += "\n".join(content.values())
            raw_text += "\n\n"

        texxt = {"text": raw_text}

        client = (
            lark.Client.builder()
            .app_id(app_key)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        request: CreateMessageRequest = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(open_id)
                .msg_type("text")
                .content(json.dumps(texxt))
                .uuid(str(uuid.uuid4()))
                .build()
            )
            .build()
        )
        response: CreateMessageResponse = client.im.v1.message.create(request)


def handler(event, context):
    logging.info(f"received new request, event content: {event}")
    config = load_config("config.yaml")
    config = {**config, "update_paper_links": False}
    demo(**config)
    result = {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"message": "Hello veFaaS!"}),
    }
    return result
