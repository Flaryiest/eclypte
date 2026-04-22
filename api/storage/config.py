from dataclasses import dataclass
import os


@dataclass(frozen=True)
class R2Config:
    account_id: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    endpoint_url: str
    region_name: str = "auto"

    @classmethod
    def from_env(cls) -> "R2Config":
        account_id = os.environ["ECLYPTE_R2_ACCOUNT_ID"]
        endpoint_url = os.environ.get(
            "ECLYPTE_R2_ENDPOINT_URL",
            f"https://{account_id}.r2.cloudflarestorage.com",
        )
        return cls(
            account_id=account_id,
            bucket=os.environ["ECLYPTE_R2_BUCKET"],
            access_key_id=os.environ["ECLYPTE_R2_ACCESS_KEY_ID"],
            secret_access_key=os.environ["ECLYPTE_R2_SECRET_ACCESS_KEY"],
            endpoint_url=endpoint_url,
            region_name=os.environ.get("ECLYPTE_R2_REGION_NAME", "auto"),
        )
