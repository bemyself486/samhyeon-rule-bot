import streamlit as st
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
import os
import glob

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

pdf_files = glob.glob("*.pdf")
DB_DIR = "faiss_index"

# 3-1. 이미 만들어둔 요약 노트가 있다면 불러오기
if os.path.exists(DB_DIR) and api_key and st.session_state.vectorstore is None:
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2", google_api_key=api_key)
    st.session_state.vectorstore = FAISS.load_local(DB_DIR, embeddings, allow_dangerous_deserialization=True)
    st.success("⚡ 구글 엔진 지식을 0.1초 만에 연결했습니다!")

# 3-2. 요약 노트가 없다면 최초 1회 만들기
elif pdf_files and api_key and st.session_state.vectorstore is None:
    with st.spinner("구글 초고속 엔진으로 요약 노트를 생성하는 중입니다..."):
        all_splits = []
        for pdf_file in pdf_files:
            loader = PyPDFLoader(pdf_file)
            docs = loader.load()
            for doc in docs:
                doc.metadata['source'] = os.path.basename(pdf_file)
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
            splits = text_splitter.split_documents(docs)
            all_splits.extend(splits)
            
        embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2", google_api_key=api_key)
        vectorstore = FAISS.from_documents(all_splits, embeddings)
        vectorstore.save_local(DB_DIR)
        
        st.session_state.vectorstore = vectorstore
        st.success("✨ 구글 엔진 전용 요약 노트 저장이 완료되었습니다!")

# 4. 과거 채팅 내용 화면에 그리기
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# 5. 질문 및 답변 로직
if st.session_state.vectorstore is not None:
    # ⭐️ 수정 1: 한 번에 가져오는 조각을 3개에서 5개로 늘려서 꼼꼼히 탐색
    retriever = st.session_state.vectorstore.as_retriever(search_kwargs={"k": 5})
    llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", google_api_key=api_key, temperature=0)

    # ⭐️ 수정 2: 선생님의 아이디어를 반영하여 프롬프트를 훨씬 유연하고 친절하게 수정
    system_prompt = (
        "당신은 교내 교사를 돕는 친절하고 꼼꼼한 업무 비서입니다. "
        "아래에 제공된 [문서 내용]을 바탕으로 질문에 답변하세요. "
        "만약 질문에 대한 '정확하고 직접적인 답변'이 문서에 없다면, 절대 지어내지 마세요. "
        "대신 \"정확한 규정을 찾을 수 없지만, 질문과 가장 관련이 깊은 유사 내용은 다음과 같습니다.\"라고 안내한 뒤, "
        "검색된 문서 내용 중 가장 참고할 만한 부분을 있는 그대로 요약해서 제공하세요. "
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
            filename = doc.metadata.get('source', '알 수 없는 파일')
            page = doc.metadata.get('page', 0) + 1 
            formatted_texts.append(f"[출처: {filename}, {page}페이지]\n{doc.page_content}")
        return "\n\n".join(formatted_texts)

    rag_chain = (
        {"context": retriever | format_docs_with_source, "input": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    user_query = st.chat_input("질문 (예: 휴대전화 사용 규정은?)")
    
    if user_query:
        st.chat_message("user").write(user_query)
        st.session_state.messages.append({"role": "user", "content": user_query})
        
        with st.chat_message("assistant"):
            # ⭐️ try-except 안전망을 설치하여 에러가 나도 앱이 죽지 않게 보호합니다.
            try:
                with st.spinner("🔍 수백 페이지의 규정집을 꼼꼼히 뒤져보는 중입니다... (약 10~15초 소요)"):
                    result = st.write_stream(rag_chain.stream(user_query))
                st.session_state.messages.append({"role": "assistant", "content": result})
                
            except Exception as e:
                # 에러가 발생하면 빨간 창 대신 아래의 부드러운 경고 메시지를 띄웁니다.
                st.warning("앗! 답변을 가져오는 중에 통신이 끊기거나 새 질문이 겹쳤습니다. 잠시 후 질문을 다시 입력해 주세요! 😅")
                
else:
    if not api_key:
        st.info("💡 왼쪽 사이드바에 Google Gemini API Key를 먼저 입력해 주세요.")
    elif not pdf_files:
        st.warning("📂 현재 폴더에 PDF 파일이 없습니다.")
