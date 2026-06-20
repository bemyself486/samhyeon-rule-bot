import streamlit as st
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os
import glob
import json
import re
from datetime import datetime

# 1. 웹앱 기본 설정
st.set_page_config(page_title="우리학교 규정찾아봇", page_icon="🏫")
st.title("🏫 우리학교 전용 규정 챗봇 (초고속 구글 엔진)")
st.write("우리 학교의 규정집들이 내장되어 있습니다. 편하게 질문해 보세요!")

# 2. 사이드바 설정
with st.sidebar:
    st.header("⚙️ 설정")
    api_key = st.text_input("Google Gemini API Key를 입력하세요", type="password")

# 세션 상태 초기화
if "vectorstore" not in st.session_state:
    st.session_state.vectorstore = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "index_status" not in st.session_state:
    st.session_state.index_status = "대기 중"

pdf_files = sorted(glob.glob("*.pdf"))
DB_DIR = "faiss_index"
MANIFEST_FILE = os.path.join(DB_DIR, "manifest.json")


def get_pdf_manifest(files):
    return [
        {
            "name": os.path.basename(file),
            "size": os.path.getsize(file),
            "mtime": os.path.getmtime(file),
        }
        for file in files
    ]


def read_manifest():
    if not os.path.exists(MANIFEST_FILE):
        return None
    with open(MANIFEST_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def write_manifest(manifest):
    os.makedirs(DB_DIR, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)


def index_files_exist():
    return (
        os.path.exists(os.path.join(DB_DIR, "index.faiss"))
        and os.path.exists(os.path.join(DB_DIR, "index.pkl"))
    )


def get_index_updated_at():
    if not os.path.exists(MANIFEST_FILE):
        return "기록 없음"
    updated_at = os.path.getmtime(MANIFEST_FILE)
    return datetime.fromtimestamp(updated_at).strftime("%Y-%m-%d %H:%M")


@st.cache_resource(show_spinner=False)
def get_embeddings(api_key):
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-2",
        google_api_key=api_key,
    )


@st.cache_resource(show_spinner=False)
def load_vectorstore(api_key, manifest_key):
    embeddings = get_embeddings(api_key)
    return FAISS.load_local(DB_DIR, embeddings, allow_dangerous_deserialization=True)


@st.cache_resource(show_spinner=False)
def build_vectorstore(api_key, files_key):
    all_splits = []
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=150)

    for pdf_file in json.loads(files_key):
        loader = PyPDFLoader(pdf_file)
        docs = loader.load()
        for doc in docs:
            doc.metadata["source"] = os.path.basename(pdf_file)
        all_splits.extend(text_splitter.split_documents(docs))

    embeddings = get_embeddings(api_key)
    vectorstore = FAISS.from_documents(all_splits, embeddings)
    vectorstore.save_local(DB_DIR)
    return vectorstore


def get_indexed_docs(vectorstore):
    docstore = getattr(vectorstore, "docstore", None)
    stored_docs = getattr(docstore, "_dict", {})
    return list(stored_docs.values())


def extract_keywords(query):
    words = re.findall(r"[0-9A-Za-z가-힣]{2,}", query.lower())
    stopwords = {"규정", "관련", "어떻게", "무엇", "있는지", "알려줘", "찾아줘"}
    return [word for word in words if word not in stopwords]


def keyword_search(query, vectorstore, limit=4):
    keywords = extract_keywords(query)
    if not keywords:
        return []

    scored_docs = []
    for doc in get_indexed_docs(vectorstore):
        content = doc.page_content.lower()
        score = sum(content.count(keyword) for keyword in keywords)
        if score:
            scored_docs.append((score, doc))

    scored_docs.sort(key=lambda item: item[0], reverse=True)
    return [doc for _, doc in scored_docs[:limit]]


def retrieve_docs(query, vectorstore):
    vector_docs = vectorstore.max_marginal_relevance_search(
        query,
        k=6,
        fetch_k=20,
    )
    keyword_docs = keyword_search(query, vectorstore, limit=4)

    merged_docs = []
    seen = set()
    for doc in vector_docs + keyword_docs:
        key = (
            doc.metadata.get("source"),
            doc.metadata.get("page"),
            doc.page_content[:120],
        )
        if key not in seen:
            seen.add(key)
            merged_docs.append(doc)

    return merged_docs[:8]


# 3. 문서 인덱스 연결
if api_key and st.session_state.vectorstore is None:
    current_manifest = get_pdf_manifest(pdf_files)
    saved_manifest = read_manifest()
    manifest_key = json.dumps(current_manifest, ensure_ascii=False, sort_keys=True)
    files_key = json.dumps(pdf_files, ensure_ascii=False)

    if index_files_exist() and saved_manifest in (None, current_manifest):
        st.session_state.vectorstore = load_vectorstore(api_key, manifest_key)
        if saved_manifest is None:
            write_manifest(current_manifest)
        st.session_state.index_status = "저장된 인덱스 연결됨"
        st.success("⚡ 저장된 문서 인덱스를 빠르게 연결했습니다!")
    elif pdf_files:
        with st.spinner("문서 변경을 반영해 검색 인덱스를 만드는 중입니다..."):
            st.session_state.vectorstore = build_vectorstore(api_key, files_key)
            write_manifest(current_manifest)
        st.session_state.index_status = "문서 변경 반영 후 새로 생성됨"
        st.success("✨ 검색 인덱스 저장이 완료되었습니다!")

with st.sidebar:
    with st.expander("🔎", expanded=False):
        st.caption(f"문서: {len(pdf_files)}개")
        st.caption(f"인덱스: {st.session_state.index_status}")
        st.caption("검색: 의미 검색 + 키워드 보강")
        st.caption(f"인덱스 파일: {'있음' if index_files_exist() else '없음'}")
        st.caption(f"마지막 갱신: {get_index_updated_at()}")

# 4. 과거 채팅 내용 화면에 그리기
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# 5. 질문 및 답변 로직
if st.session_state.vectorstore is not None:
    llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", google_api_key=api_key, temperature=0)

    system_prompt = (
        "당신은 교내 교사를 돕는 친절하고 꼼꼼한 업무 비서입니다. "
        "아래에 제공된 [문서 내용]을 바탕으로 질문에 답변하세요. "
        "만약 질문에 대한 '정확하고 직접적인 답변'이 문서에 없다면, 절대 지어내지 마세요. "
        "대신 \"정확한 규정을 찾을 수 없지만, 질문과 가장 관련이 깊은 유사 내용은 다음과 같습니다.\"라고 안내한 뒤, "
        "검색된 문서 내용 중 가장 참고할 만한 부분을 있는 그대로 요약해서 제공하세요. "
        "질문과 같은 키워드가 문서 내용에 보이면 그 부분을 우선 근거로 삼으세요. "
        "정확한 답변이든, 유사 내용 제공이든 반드시 맨 마지막에 근거가 된 [출처 파일명]과 [페이지 번호]를 명시하세요.\n\n"
        "[문서 내용]\n"
        "{context}"
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
    ])

    def format_docs_with_source(docs):
        formatted_texts = []
        for doc in docs:
            filename = doc.metadata.get("source", "알 수 없는 파일")
            page = doc.metadata.get("page", 0) + 1
            formatted_texts.append(f"[출처: {filename}, {page}페이지]\n{doc.page_content}")
        return "\n\n".join(formatted_texts)

    rag_chain = prompt | llm | StrOutputParser()

    user_query = st.chat_input("질문 (예: 휴대전화 사용 규정은?)")

    if user_query:
        st.chat_message("user").write(user_query)
        st.session_state.messages.append({"role": "user", "content": user_query})

        with st.chat_message("assistant"):
            try:
                with st.spinner("🔍 수백 페이지의 규정집을 꼼꼼히 뒤져보는 중입니다... (약 10~15초 소요)"):
                    docs = retrieve_docs(user_query, st.session_state.vectorstore)
                    context = format_docs_with_source(docs)
                    result = st.write_stream(rag_chain.stream({"context": context, "input": user_query}))
                st.session_state.messages.append({"role": "assistant", "content": result})
            except Exception as e:
                st.warning("앗! 답변을 가져오는 중에 통신이 끊기거나 새 질문이 겹쳤습니다. 잠시 후 질문을 다시 입력해 주세요! 😅")
                with st.expander("🛠️ (관리자용) 상세 에러 원인 보기"):
                    st.error(f"실제 에러 내용: {e}")
                print(f"🚨 챗봇 에러 발생: {e}")
else:
    if not api_key:
        st.info("💡 왼쪽 사이드바에 Google Gemini API Key를 먼저 입력해 주세요.")
    elif not pdf_files:
        st.warning("📂 현재 폴더에 PDF 파일이 없습니다.")
