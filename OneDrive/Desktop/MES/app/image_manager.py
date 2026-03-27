# image_manager.py
# Handles product image compression and upload to Supabase Storage.
# Images are compressed with Pillow, uploaded to a "product-images" bucket,
# and their public URLs are stored in the products table.

import io
import uuid

import streamlit as st
from PIL import Image

from app.supabase_client import get_authed_supabase


BUCKET_NAME = "product-images"
MAX_DIMENSION = 1200  # Max width or height in pixels
JPEG_QUALITY = 80     # Compression quality (1-100)


def _ensure_bucket_exists(sb) -> bool:
    """Check if the product-images bucket exists, create it if not.

    Returns True if bucket is available, False on failure.
    """
    try:
        buckets = sb.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        if BUCKET_NAME not in bucket_names:
            sb.storage.create_bucket(BUCKET_NAME, options={"public": True})
        return True
    except Exception as e:
        st.error(
            f"Could not access Supabase Storage: {e}\n\n"
            "Make sure your Supabase project has Storage enabled. "
            "Go to **Storage** in your Supabase dashboard and create a bucket named "
            f"`{BUCKET_NAME}` with **public** access."
        )
        return False


def compress_image(image_bytes: bytes, filename: str) -> tuple[bytes, str]:
    """Compress an image to JPEG, resize if too large.

    Returns (compressed_bytes, output_filename).
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Convert to RGB if necessary (handles PNG with alpha, etc.)
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize if exceeds max dimension
    width, height = img.size
    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        ratio = min(MAX_DIMENSION / width, MAX_DIMENSION / height)
        new_size = (int(width * ratio), int(height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Compress to JPEG
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    buffer.seek(0)

    # Always output as .jpg
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    output_filename = f"{base}.jpg"

    return buffer.getvalue(), output_filename


def upload_image_to_supabase(
    image_bytes: bytes,
    filename: str,
    sku: str,
) -> str | None:
    """Compress and upload an image to Supabase Storage.

    The file is stored at: product-images/{sku}/{unique_id}_{filename}
    Returns the public URL on success, None on failure.
    """
    sb = get_authed_supabase()

    if not _ensure_bucket_exists(sb):
        return None

    compressed, output_name = compress_image(image_bytes, filename)

    # Unique path to avoid collisions
    unique_id = uuid.uuid4().hex[:8]
    storage_path = f"{sku}/{unique_id}_{output_name}"

    try:
        sb.storage.from_(BUCKET_NAME).upload(
            storage_path,
            compressed,
            file_options={"content-type": "image/jpeg"},
        )
    except Exception as e:
        # If file already exists, try removing and re-uploading
        if "Duplicate" in str(e) or "already exists" in str(e):
            try:
                sb.storage.from_(BUCKET_NAME).remove([storage_path])
                sb.storage.from_(BUCKET_NAME).upload(
                    storage_path,
                    compressed,
                    file_options={"content-type": "image/jpeg"},
                )
            except Exception as retry_e:
                st.error(f"Failed to upload image: {retry_e}")
                return None
        else:
            st.error(f"Failed to upload image: {e}")
            return None

    # Get public URL
    public_url = sb.storage.from_(BUCKET_NAME).get_public_url(storage_path)
    return public_url


def delete_image_from_supabase(url: str) -> bool:
    """Delete an image from Supabase Storage by its public URL.

    Returns True on success.
    """
    if not url or url in ("N/A", ""):
        return True

    sb = get_authed_supabase()

    # Extract path from public URL
    # URL format: https://xxx.supabase.co/storage/v1/object/public/product-images/sku/file.jpg
    try:
        marker = f"/storage/v1/object/public/{BUCKET_NAME}/"
        if marker in url:
            path = url.split(marker, 1)[1]
            sb.storage.from_(BUCKET_NAME).remove([path])
            return True
    except Exception:
        pass
    return False


def show_product_image_manager():
    """Render the product image management UI.

    Allows uploading, viewing, and replacing product images.
    Images are compressed and stored in Supabase Storage.
    """
    st.header("Product Images")
    st.markdown(
        "Upload product images here. Images are automatically compressed and stored in Supabase. "
        "When you send order emails, these images are attached to each order."
    )

    sb = get_authed_supabase()

    # Load products
    resp = sb.table("products").select("sku, name, image_url, secondary_image_url").execute()
    products = resp.data

    if not products:
        st.warning("No products found. Add products to your Supabase `products` table first.")
        return

    # Search
    search = st.text_input("Search products by name or SKU", key="img_search")

    filtered = products
    if search:
        search_lower = search.lower()
        filtered = [
            p for p in products
            if search_lower in p.get("name", "").lower()
            or search_lower in p.get("sku", "").lower()
        ]

    if not filtered:
        st.info("No matching products.")
        return

    st.caption(f"Showing {len(filtered)} product(s)")

    for product in filtered:
        sku = product["sku"]
        name = product.get("name", sku)
        img_url = product.get("image_url") or "N/A"
        secondary_url = product.get("secondary_image_url") or "N/A"

        with st.container(border=True):
            st.markdown(f"### {name}")
            st.caption(f"SKU: `{sku}`")

            img_col1, img_col2 = st.columns(2)

            # Primary image
            with img_col1:
                st.markdown("**Primary Image**")
                if img_url not in ("N/A", "", None):
                    st.image(img_url, width=200)
                else:
                    st.info("No primary image")

                uploaded_1 = st.file_uploader(
                    "Upload primary image",
                    type=["jpg", "jpeg", "png", "webp"],
                    key=f"img1_{sku}",
                    label_visibility="collapsed",
                )
                if uploaded_1 is not None:
                    if st.button("Save Primary", key=f"save1_{sku}", type="primary"):
                        with st.spinner("Compressing & uploading..."):
                            url = upload_image_to_supabase(
                                uploaded_1.getvalue(),
                                uploaded_1.name,
                                sku,
                            )
                            if url:
                                # Delete old image if it exists
                                if img_url not in ("N/A", "", None):
                                    delete_image_from_supabase(img_url)
                                sb.table("products").update(
                                    {"image_url": url}
                                ).eq("sku", sku).execute()
                                st.cache_data.clear()
                                st.success("Primary image uploaded!")
                                st.rerun()

            # Secondary image
            with img_col2:
                st.markdown("**Secondary Image**")
                if secondary_url not in ("N/A", "", None):
                    st.image(secondary_url, width=200)
                else:
                    st.info("No secondary image")

                uploaded_2 = st.file_uploader(
                    "Upload secondary image",
                    type=["jpg", "jpeg", "png", "webp"],
                    key=f"img2_{sku}",
                    label_visibility="collapsed",
                )
                if uploaded_2 is not None:
                    if st.button("Save Secondary", key=f"save2_{sku}", type="primary"):
                        with st.spinner("Compressing & uploading..."):
                            url = upload_image_to_supabase(
                                uploaded_2.getvalue(),
                                uploaded_2.name,
                                sku,
                            )
                            if url:
                                if secondary_url not in ("N/A", "", None):
                                    delete_image_from_supabase(secondary_url)
                                sb.table("products").update(
                                    {"secondary_image_url": url}
                                ).eq("sku", sku).execute()
                                st.cache_data.clear()
                                st.success("Secondary image uploaded!")
                                st.rerun()


def show_bulk_image_upload():
    """Bulk upload section — upload multiple product images at once.

    File names must start with the SKU (e.g., "SKU123_front.jpg").
    """
    st.subheader("Bulk Upload")
    st.markdown(
        "Upload multiple images at once. File names **must start with the SKU** "
        "followed by an underscore (e.g., `SKU123_front.jpg`). "
        "The first image per SKU goes to primary, the second to secondary."
    )

    files = st.file_uploader(
        "Drop product images here",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="bulk_upload",
    )

    if not files:
        return

    sb = get_authed_supabase()
    resp = sb.table("products").select("sku").execute()
    valid_skus = {row["sku"] for row in resp.data}

    # Group files by SKU prefix
    sku_files: dict[str, list] = {}
    unmatched = []

    for f in files:
        parts = f.name.split("_", 1)
        if len(parts) >= 2 and parts[0] in valid_skus:
            sku_files.setdefault(parts[0], []).append(f)
        else:
            unmatched.append(f.name)

    if unmatched:
        st.warning(f"Could not match these files to a SKU: {', '.join(unmatched)}")

    if not sku_files:
        st.info("No files matched any product SKU.")
        return

    st.markdown(f"Matched **{sum(len(v) for v in sku_files.values())}** file(s) across **{len(sku_files)}** SKU(s).")

    if st.button("Upload All Matched Images", type="primary"):
        progress = st.progress(0, text="Uploading...")
        total = sum(len(v) for v in sku_files.values())
        done = 0

        for sku, file_list in sku_files.items():
            for idx, f in enumerate(file_list[:2]):  # Max 2 images per SKU
                url = upload_image_to_supabase(f.getvalue(), f.name, sku)
                if url:
                    field = "image_url" if idx == 0 else "secondary_image_url"
                    sb.table("products").update({field: url}).eq("sku", sku).execute()
                done += 1
                progress.progress(done / total, text=f"Uploaded {done}/{total}")

        st.cache_data.clear()
        progress.empty()
        st.success(f"Uploaded images for {len(sku_files)} product(s).")
        st.rerun()
