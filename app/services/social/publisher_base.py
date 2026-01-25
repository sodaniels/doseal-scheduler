class SocialPublisherBase:
    PLATFORM = None

    def __init__(self, account_doc: dict):
        self.account = account_doc