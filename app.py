import streamlit as st
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.embeddings import HuggingFaceEmbeddings # ⭐️ 다시 안정적인 허깅페이스로 복구
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
st.title("🏫 우리학교 전용 규정 챗봇")
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

# 3-1. 이미 만들어둔 요약 노트가 있다면 1초 만에 불러오기
if os.path.exists(DB_DIR) and api_key and st.session_state.vectorstore is None:
    embeddings = HuggingFaceEmbeddings(
        model_name="jhgan/ko-sroberta-multitask",
        encode_kwargs={'normalize_embeddings': True}
    )
    st.session_state.vectorstore = FAISS.load_local(DB_DIR, embeddings, allow_dangerous_deserialization=True)
    st.success("⚡ 저장된 규정집 지식을 1초 만에 불러왔습니다!")

# 3-2. 요약 노트가 없다면 최초 1회 만들기
elif pdf_files and api_key and st.session_state.vectorstore is None:
    with st.spinner("학교 문서를 정독하여 요약 노트를 만드는 중입니다..."):
        all_splits = []
        for pdf_file in pdf_files:
            loader = PyPDFLoader(pdf_file)
            docs = loader.load()
            for doc in docs:
                doc.metadata['source'] = os.path.basename(pdf_file)
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
            splits = text_splitter.split_documents(docs)
            all_splits.extend(splits)
            
        embeddings = HuggingFaceEmbeddings(
            model_name="jhgan/ko-sroberta-multitask",
            encode_kwargs={'normalize_embeddings': True}
        )
        
        vectorstore = FAISS.from_documents(all_splits, embeddings)
        vectorstore.save_local(DB_DIR)
        
        st.session_state.vectorstore = vectorstore
        st.success("✨ 요약 노트 저장이 완료되었습니다!")

# 4. 과거 채팅 내용 화면에 그리기
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# 5. 질문 및 답변 로직
if st.session_state.vectorstore is not None:
    retriever = st.session_state.vectorstore.as_retriever(search_kwargs={"k": 3})
    llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", google_api_key=api_key, temperature=0)

    system_prompt = (
        "당신은 교내 교사를 돕는 철저하고 정확한 업무 비서입니다. "
        "아래에 제공된 [문서 내용]만을 100% 근거하여 답변하세요. "
        "만약 제공된 문서 내용에 질문에 대한 답변이 없다면, 절대 지어내지 말고 '제공된 학교 규정집에서는 해당 내용을 찾을 수 없습니다.'라고 단호하게 답변하세요. "
        "답변이 가능한 경우에만 맨 마지막에 근거가 된 [출처 파일명]과 [페이지 번호]를 명시하세요.\n\n"
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

    user_query = st.chat_input("질문 (예: 1학년 현장체험학습 규정은?)")
    
    if user_query:
        st.chat_message("user").write(user_query)
        st.session_state.messages.append({"role": "user", "content": user_query})
        
        with st.chat_message("assistant"):
            # ⭐️ 비법 2: 타자 치듯 실시간 스트리밍 출력 (속도감 대폭 상승)
            result = st.write_stream(rag_chain.stream(user_query))
            st.session_state.messages.append({"role": "assistant", "content": result})
else:
    if not api_key:
        st.info("💡 왼쪽 사이드바에 Google Gemini API Key를 먼저 입력해 주세요.")
    elif not pdf_files:
        st.warning("📂 현재 폴더에 PDF 파일이 없습니다.")