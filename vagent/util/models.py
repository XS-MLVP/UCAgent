#coding=utf-8


from .config import Config


def get_chat_model_openai(cfg: Config):
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError("Please install langchain_openai to use OpenAI chat model. "
                          "You can install it with: pip install langchain_openai")
    return ChatOpenAI(openai_api_key=cfg.openai.openai_api_key,
                                    openai_api_base=cfg.openai.openai_api_base,
                                    model=cfg.openai.model_name,
                                    seed=cfg.seed,
                                    )


def get_chat_model_anthropic(cfg: Config):
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise ImportError("Please install langchain_anthropic to use Anthropic chat model. "
                          "You can install it with: pip install langchain_anthropic")
    llm = ChatAnthropic(
        **cfg.anthropic.as_dict()
    )
    return llm


def get_chat_model_google_genai(cfg: Config):
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        raise ImportError("Please install langchain_google_genai to use Google GenAI chat model. "
                          "You can install it with: pip install langchain_google_genai")
    return ChatGoogleGenerativeAI(**cfg.google_genai.as_dict())


def get_chat_model(cfg: Config):
    model_type = cfg.get_value("model_type", "openai")
    func = "get_chat_model_%s" % model_type
    if func in globals():
        return globals()[func](cfg)
    else:
        raise ValueError(f"Unsupported model type: {model_type}. Supported types are: "
                         f"{', '.join([ f.removeprefix('get_chat_model_') for f in globals().keys() if f.startswith('get_chat_model_') ])}.")
