import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "catalog" / "suppliers.json"


def load_catalog():
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def product_index():
    catalog = load_catalog()
    return {product["key"]: product for product in catalog.get("products", [])}


def get_product(product_key):
    return product_index().get(product_key)


def all_offers():
    catalog = load_catalog()
    for product in catalog.get("products", []):
        for offer in product.get("offers", []):
            yield product, offer


def get_offer(offer_id):
    for product, offer in all_offers():
        if offer["id"] == offer_id:
            return product, offer
    return None, None


def currency():
    return load_catalog().get("currency", "USD")


def index_meta():
    catalog = load_catalog()
    return {
        "version": catalog.get("version"),
        "currency": catalog.get("currency", "USD"),
        "index_name": catalog.get("index_name", "TaskVault supplier index"),
        "product_count": len(catalog.get("products", [])),
        "offer_count": sum(len(product.get("offers", [])) for product in catalog.get("products", [])),
        "is_demo": bool(catalog.get("is_demo", False)),
    }
